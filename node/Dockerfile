FROM python:latest

ADD requirements.txt /node/
WORKDIR /node/
RUN pip3 install -r requirements.txt
ADD node.py /node/
ADD message.py /node/