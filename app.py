from flask import Flask, render_template, request, jsonify, redirect, url_for
import gspread, os, json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import paho.mqtt.publish as publish

app = Flask(__name__)

# ==========================
# MQTT 設定
# ==========================
MQTT_HOST = "broker.hivemq.com"
MQTT_TOPIC = "m5stack/test"
MQTT_PORT = 1883

# ==========================
# Google スプレッドシート接続
# ==========================
scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
creds_json = os.getenv("GOOGLE_CREDENTIALS")
credentials = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
gc = gspread.authorize(credentials)

sh = gc.open("自販機管理")
sheet_stock = sh.worksheet("在庫管理")
sheet_users = sh.worksheet("利用者")
sheet_log = sh.worksheet("販売履歴")

def get_col_index(sheet, column_name):
    header = sheet.row_values(1)
    return header.index(column_name) + 1

COL_NAME = get_col_index(sheet_stock, "商品名")
COL_STOCK = get_col_index(sheet_stock, "在庫")
COL_PRICE = get_col_index(sheet_stock, "価格")

# ==========================
# LIFF 起動ルート
# ==========================
@app.route("/liff")
def liff_entry():
    return render_template("check.html")

# ==========================
# 利用者判定 API（LIFF から userId を送信）
# ==========================
@app.route("/check_user", methods=["POST"])
def check_user():
    data = request.json
    line_user_id = data.get("userId")
    if not line_user_id:
        return jsonify({"status":"error","message":"LINE ID が取得できません"})

    all_users = sheet_users.get_all_records()
    for u in all_users:
        if str(u["ID"]).strip() == line_user_id:
            return jsonify({"status":"ok","registered":True,"name":u["氏名"]})
    return jsonify({"status":"ok","registered":False})

# ==========================
# 会員登録 POST
# ==========================
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    name = data.get("name")
    student_id = data.get("student_id")
    grade = data.get("grade")
    line_user_id = data.get("userId")

    if not all([name, student_id, grade, line_user_id]):
        return jsonify({"status":"error","message":"入力が不完全です"})

    # 重複チェック
    all_users = sheet_users.get_all_records()
    for u in all_users:
        if str(u["ID"]).strip() == line_user_id:
            return jsonify({"status":"error","message":"このLINEアカウントはすでに登録済みです"})

    sheet_users.append_row([name, student_id, grade, line_user_id])
    return jsonify({"status":"ok","message":f"{name} さんを登録しました"})

# ==========================
# index ページ（販売画面）
# ==========================
@app.route('/')
def index():
    items = sheet_stock.get_all_records()
    return render_template("index.html", items=items)

# ==========================
# その他 API（購入・在庫・ping） は既存コードのまま
# ==========================

# 例: /buy
@app.route("/buy", methods=["POST"])
def buy_item():
    data = request.json
    item_name = data.get("item_name")
    user_id = str(data.get("user_id")).strip()

    # 利用者検索
    users = sheet_users.get_all_records()
    user_name = "不明"
    for u in users:
        if str(u["ID"]).strip() == user_id:
            user_name = u["氏名"]
            break

    all_stock = sheet_stock.get_all_records()
    for i, row in enumerate(all_stock, start=2):
        if row["商品名"] == item_name:
            stock = row["在庫"]
            price = row["価格"]
            shelf = row.get("棚番号","")
            address = row.get("アドレス","")

            if stock <=0:
                return jsonify({"status":"error","message":"在庫がありません"})

            new_stock = stock - 1
            sheet_stock.update_cell(i, COL_STOCK, new_stock)

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet_log.append_row([now, user_name, item_name, price])

            try:
                publish.single(MQTT_TOPIC, payload=str(shelf)+str(address), hostname=MQTT_HOST, port=MQTT_PORT)
                mqtt_status="ok"
            except Exception as e:
                mqtt_status=f"error: {str(e)}"

            return jsonify({"status":"ok","message":f"{item_name} を購入しました","new_stock":new_stock,"price":price,"mqtt":mqtt_status})
    return jsonify({"status":"error","message":"商品が見つかりません"})


# ==========================
# JSON 在庫 API
# ==========================
@app.route("/stock", methods=["GET"])
def get_stock():
    data = sheet_stock.get_all_records()
    return jsonify({"items":data})

@app.route("/ping")
def ping():
    return "ok"

if __name__ == "__main__":
    app.run(port=5000, debug=True)
