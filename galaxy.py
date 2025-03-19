#!/usr/bin/python
import re
import socket
import ssl
import base64
import time
import requests
import string
import queue
import multiprocessing
import sys
import json

global result_queue
result_queue = multiprocessing.Queue()

class SimpleIRCBot:
    def __init__(self, server, port, channel, nick, username, password):
        self.server = server
        self.port = port
        self.channel = channel
        self.nick = nick
        self.username = username
        self.password = password
        self.irc = None
        self.model = "gemma2"
        self.running = True

    def connect(self):
        # Create a raw socket and wrap it with SSL
        print(f"Connecting to {self.server} on port {self.port} with SSL...")
        raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        context = ssl.create_default_context()
        self.irc = context.wrap_socket(raw_socket, server_hostname=self.server)
        self.irc.connect((self.server, self.port))

        # Request CAP (capabilities)
        self.irc.send(bytes(f"CAP LS\n", "UTF-8"))

        # Send user and nick commands
        self.irc.send(bytes(f"NICK {self.nick}\n", "UTF-8"))
        self.irc.send(bytes(f"USER {self.username} 0 * :IRC Bot\n", "UTF-8"))

        cookie = None

        while True:
            response = self.irc.recv(4096).decode("UTF-8").strip('\n\r')
            if response:
                print(response)

            pattern = r'PING :(\w+)'
            match = re.search(pattern, response)
            if match:
                cookie = match.group(1)

            if "PING" in response:
                print("response" + str({response.split()[1]}))
                self.irc.send(bytes(f"PONG :{response.split()[1]}\n", "UTF-8"))

            # If CAP LS is acknowledged, request SASL
            if "CAP * LS" in response:
                self.irc.send(bytes("CAP REQ :sasl\n", "UTF-8"))

            # If CAP ACK is received, initiate SASL authentication
            if "CAP Galaxy ACK :sasl" in response:
                print("SASL acknowledged, initiating authentication...")
                self.irc.send(bytes("AUTHENTICATE PLAIN\n", "UTF-8"))

            # Send base64 encoded credentials after receiving a + from the server
            if "AUTHENTICATE +" in response:
                auth_token = base64.b64encode(f"{self.username}\0{self.username}\0{self.password}".encode()).decode("UTF-8")
                print(f"Sending encoded credentials: {auth_token}")
                self.irc.send(bytes(f"AUTHENTICATE {auth_token}\n", "UTF-8"))

            # Successful authentication
            if "903" in response or "900" in response:  # 900 = SASL logged in, 903 = SASL success
                print("SASL authentication successful!")
                self.irc.send(bytes("CAP END\n", "UTF-8"))
                self.irc.send(bytes(f"PONG {cookie}\n", "UTF-8"))
                #time.sleep(5)
                break

            # Authentication failed
            if "904" in response or "905" in response:  # 904 = SASL failed, 905 = SASL error
                print("SASL authentication failed.")
                self.irc.close()
                return


    def handle_ping(self):
        """Separate thread to listen for and respond to PINGs."""
        while self.running:
            try:
                response = self.irc.recv(2048).decode("UTF-8").strip("\n\r")
                if "PING" in response:
                    print("We got a ping!")
                    self.irc.send(bytes(f"PONG {response.split()[1]}\n", "UTF-8"))
            except Exception as e:
                print(f"Ping handler error: {e}")

    def listen(self):
        time.sleep(2)
        self.irc.send(bytes(f"JOIN {self.channel}\n", "UTF-8"))


        # Start a thread to handle PINGs separately
        #ping_thread = threading.Thread(target=self.handle_ping, daemon=True)
        #ping_thread.start()

        while True:
            try:
                response = self.irc.recv(2048).decode("UTF-8").strip('\n\r')

                if response.startswith("PING"):
                    self.irc.send(bytes(f"PONG {response.split()[1]}\n", "UTF-8"))

                if "PRIVMSG" in response and f"PRIVMSG {self.channel}" in response:
                    message = response.split(f"PRIVMSG {self.channel} :")[1]
                    print(f"Message received: {message}")

                    if message.startswith(">>>"):
                        #reply = self.get_ollama_response("Respond in under 400 characters:" + message[3:])
                        #thread = threading.Thread(target=self.get_ollama_response, args=("Respond in under 400 characters:" + message[3:], ))
                        process = multiprocessing.Process(target=self.get_ollama_response, args=("Respond in under 400 characters:" + message[3:], ))
                        process.start()
                        reply = []
                    #thread.join()
#                    while not result_queue.empty():
#                        reply.append(result_queue.get())
#
#                    if self.model == "deepseek-r1:latest" or self.model == "deepseek-r1":
#                        stripped = re.sub(r'<think>.*?</think>', '', reply[0].replace("\n", " "))
#                        reply = stripped
#                        self.send_message(reply.replace("\n", " "))
#                    else:
#                        self.send_message(reply[0].replace("\n", " "))


                    if message.lower().startswith("!lm"):
                        response = requests.get("http://localhost:11434/api/tags").json()
                        names = [model["name"] for model in response["models"]]
                        names_string = ", ".join(names)
                        self.send_message(names_string)

                    if message.lower().startswith("!sm"):
                        self.model = message[4:]

                    if message.lower().startswith("!help"):
                       self.send_message("!lm (list models), !sm <model> (switch models)")


                   # Retrieve Ollama response if available
                    while not result_queue.empty():
                        reply = result_queue.get()
                        if self.model == "deepseek-r1:latest" or self.model == "deepseek-r1":
                            stripped = re.sub(r'<think>.*?</think>', '', reply.replace("\n", " "))
                            reply = stripped
                        self.send_message(reply.replace("\n", " "))

            except Exception as e:
                print(f"Error in listen loop: {e}")


    def get_ollama_response(self, message):
        print(f"Sending message to ollama: {message}")
        headers = {
            "Content-Type": "application/json",
        }
        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": message}],
            "stream": False
        }

        response = requests.post("http://localhost:11434/api/chat", headers=headers, json=data)
        if response.status_code == 200:
            result_queue.put(str(response.json()["message"]["content"]))
        else:
            print(f"Error from ollama: {response.status_code} - {response.text}")
            result_queue.put("Sorry, I couldn't process that request.")

    def send_message(self, message):
        chunks = self.split_message(message)
        for chunk in chunks:
            self.irc.send(bytes(f"PRIVMSG {self.channel} :{chunk}\n", "UTF-8"))
            print(f"Sent message: {chunk}")
            time.sleep(2)

    def split_message(self, message):
        """Split the message into chunks that fit within the IRC limit."""
        return [message[i:i+400] for i in range(0, len(message), 400)]

def main():
    if len(sys.argv) < 2:
        print("Usage: python galaxy.py <config_file>")
        sys.exit(1)

    try:
        with open(sys.argv[1], 'r') as file:
            config = json.load(file)

    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON: {e}")

    for key, value in config.items():
        bot = SimpleIRCBot(
	    server=value.get("server"),
	    port=int(value.get("port")),
	    channel=value.get("channels"),
	    nick=value.get("nick"),
	    username=value.get("username"),
	    password=value.get("password")
       )

    bot.connect()
    bot.listen()

if __name__ == "__main__":
    main()
