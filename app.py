from flask import Flask, render_template, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import json

# ==========================
# MQTT 設定
# ==========================
import paho.mqtt.client as mqtt
BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC = "m5stack/test"
client = mqtt.Client()
client.connect(BROKER, PORT, 60)


app = Flask(__name__)

# ==========================
# Google スプレッドシート接続（Render 対応）
# ==========================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Render の環境変数 GOOGLE_CREDENTIALS を JSON として読み込む
creds_json = os.getenv("GOOGLE_CREDENTIALS")
if not creds_json:
    raise RuntimeError("環境変数 GOOGLE_CREDENTIALS が設定されていません")

credentials = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(creds_json), scope
)
gc = gspread.authorize(credentials)

# シート取得
sh = gc.open("自販機管理")
sheet_stock = sh.worksheet("在庫管理")
sheet_users = sh.worksheet("利用者")
sheet_log = sh.worksheet("販売履歴")


# ==========================
# ヘッダ行から列番号取得
# ==========================
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
# 購入 API
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

    for i, row in enumerate(all_stock, start=2):  # データは2行目から
        if row["商品名"] == item_name:
            stock = row["在庫"]
            price = row["価格"]
            address = row["アドレス"]

            if stock <= 0:
                return jsonify({"status": "error", "message": "在庫がありません"})

            # 在庫減算
            new_stock = stock - 1
            sheet_stock.update_cell(i, COL_STOCK, new_stock)

            # MQTT にアドレス送信
            client.publish(TOPIC, address)
            print("MQTT → 自販機にアドレス送信:", address)

            # 販売履歴追加
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet_log.append_row([now, user_name, item_name, price])

            return jsonify({
                "status": "ok",
                "message": f"{item_name} を購入しました",
                "new_stock": new_stock,
                "price": price
            })

    return jsonify({"status": "error", "message": "商品が見つかりません"})


# ==========================
# JSON 在庫 API
# ==========================
@app.route("/stock", methods=["GET"])
def get_stock():
    data = sheet_stock.get_all_records()
    return jsonify({"items": data})


# ==========================
# Render のヘルスチェック用
# ==========================
@app.route("/ping")
def ping():
    return "ok"


if __name__ == "__main__":
    app.run(port=5000, debug=True)
