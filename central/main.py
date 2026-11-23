import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags, reason_code, properties):
    print("접속 결과: ", reason_code)
    client.subscribe("stillsafe/#")


def on_message(client, userdata, msg):
    print(msg.topic, msg.payload.decode())


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883)
client.loop_forever()