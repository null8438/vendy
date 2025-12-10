from flask import Flask, render_template, request, jsonify
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import paho.mqtt.client as mqtt

app = Flask(__name__)

# ==========================
# Google Sheets 認証（遅延）
# ==========================
def get_gsheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    # credentials.json を環境変数から読む（Render推奨）
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    creds_dict = json.loads(creds_json)

    credentials = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_dict, scope
    )
    gc = gspread.authorize(credentials)
    sh = gc.open("自販機管理")
    return {
        "stock": sh.worksheet("在庫管理"),
        "users": sh.worksheet("利用者"),
        "log": sh.worksheet("販売履歴")
    }

# ==========================
# MQTT（遅延接続）
# ==========================
def get_mqtt_client():
    client = mqtt.Client()
    client.connect("broker.hivemq.com", 1883, 60)
    return client


# ==========================
# HTML 表示
# ==========================
@app.route("/")
def index():
    gs = get_gsheet()
    items = gs["stock"].get_all_records()
    return render_template("index.html", items=items)


# ==========================
# 購入 API
# ==========================
@app.route("/buy", methods=["POST"])
def buy_item():
    data = request.json
    item_name = data.get("item_name")
    user_id = str(data.get("user_id")).strip()

    gs = get_gsheet()
    stock_sheet = gs["stock"]
    users_sheet = gs["users"]
    log_sheet = gs["log"]

    # 利用者検索
    users = users_sheet.get_all_records()
    user_name = next(
        (u["氏名"] for u in users if str(u["ID"]).strip() == user_id),
        "不明"
    )

    # 在庫データ
    all_stock = stock_sheet.get_all_records()

    for i, row in enumerate(all_stock, start=2):
        if row["商品名"] == item_name:
            stock = row["在庫"]
            price = row["価格"]
            address = row["アドレス"]

            if stock <= 0:
                return jsonify({"status": "error", "message": "在庫がありません"})

            # 在庫更新
            stock_sheet.update_cell(i, row.keys().index("在庫") + 1, stock - 1)

            # MQTT publish
            client = get_mqtt_client()
            client.publish("m5stack/test", address)

            # 履歴
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_sheet.append_row([now, user_name, item_name, price])

            return jsonify({"status": "ok", "message": "購入完了"})

    return jsonify({"status": "error", "message": "商品が見つかりません"})


@app.route("/stock")
def stock():
    gs = get_gsheet()
    data = gs["stock"].get_all_records()
    return jsonify({"items": data})


@app.route("/ping")
def ping():
    return "ok"


# Render はここを使わない（gunicorn使用）
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
