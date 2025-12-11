from flask import Flask, render_template, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import json

# MQTT ---------------------------------------------------------
import paho.mqtt.publish as publish

MQTT_HOST = "broker.hivemq.com"  # xxxxxx.s1.eu.hivemq.cloud
MQTT_TOPIC = "m5stack/test"
MQTT_PORT = 1883
# --------------------------------------------------------------

app = Flask(__name__)

# ==========================
# Google スプレッドシート接続（Render 対応）
# ==========================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds_json = os.getenv("GOOGLE_CREDENTIALS")
if not creds_json:
    raise RuntimeError("環境変数 GOOGLE_CREDENTIALS が設定されていません")

credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(creds_json), scope
)
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
# index ページ
# ==========================
@app.route('/')
def index():
    items = sheet_stock.get_all_records()
    return render_template("index.html", items=items)

# ==========================
# LIFF 起動用ルート（LINE userId で分岐）
# ==========================
@app.route("/liff")
def liff_entry():
    line_user_id = request.args.get("userId")
    if not line_user_id:
        return "LINE ID が取得できません"

    # Googleスプレッドシートに登録済みか確認
    all_users = sheet_users.get_all_records()
    for u in all_users:
        if str(u["ID"]).strip() == line_user_id:
            # 登録済 → index.html に購入画面を表示
            return render_template("index.html", user_name=u["氏名"])

    # 未登録 → 会員登録フォームを表示
    return render_template("register.html", line_user_id=line_user_id)


# ==========================
# 会員登録 POST
# ==========================
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    name = data.get("name")
    student_id = data.get("student_id")
    grade = data.get("grade")
    line_user_id = request.headers.get("X-LINE-USER-ID")

    if not all([name, student_id, grade, line_user_id]):
        return jsonify({"status":"error","message":"入力が不完全です"})

    # 重複チェック
    all_users = sheet_users.get_all_records()
    for u in all_users:
        if str(u["ID"]).strip() == line_user_id:
            return jsonify({"status":"error","message":"このLINEアカウントはすでに登録済みです"})

    # スプレッドシートに追加（氏名、学籍番号、学年、ID）
    sheet_users.append_row([name, student_id, grade, line_user_id])

    return jsonify({"status":"ok","message":f"{name} さんを登録しました"})


# ==========================
# 購入 API（ここで MQTT 送信！）
# ==========================
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

    # 在庫検索
    all_stock = sheet_stock.get_all_records()

    for i, row in enumerate(all_stock, start=2):
        if row["商品名"] == item_name:
            stock = row["在庫"]
            price = row["価格"]
            shelf = row["棚番号"]
            address = row["アドレス"]

            if stock <= 0:
                return jsonify({"status": "error", "message": "在庫がありません"})

            # 在庫減らす
            new_stock = stock - 1
            sheet_stock.update_cell(i, COL_STOCK, new_stock)

            # 履歴追加
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet_log.append_row([now, user_name, item_name, price])

            # ==========================
            # 🔥 MQTT プッシュ
            # ==========================
            try:
                publish.single(
                    MQTT_TOPIC,
                    payload=str(shelf)+str(address),       # ← ESP32 に送る値
                    hostname=MQTT_HOST,
                    port=MQTT_PORT,
                )
                mqtt_status = "ok"
            except Exception as e:
                mqtt_status = f"error: {str(e)}"

            return jsonify({
                "status": "ok",
                "message": f"{item_name} を購入しました",
                "new_stock": new_stock,
                "price": price,
                "mqtt": mqtt_status
            })

    return jsonify({"status": "error", "message": "商品が見つかりません"})


# ==========================
# JSON 在庫 API
# ==========================
@app.route("/stock", methods=["GET"])
def get_stock():
    data = sheet_stock.get_all_records()
    return jsonify({"items": data})


@app.route("/ping")
def ping():
    return "ok"


if __name__ == "__main__":
    app.run(port=5000, debug=True)
