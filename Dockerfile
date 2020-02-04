FROM faucet/python3:4.0.0

COPY ./ /pipette-src/

RUN apk add gcc python3-dev musl-dev && \
        pip3 install -r pipette-src/requirements.txt && \
        apk del gcc python3-dev musl-dev

EXPOSE 6653

CMD ["ryu-manager", "/pipette-src/pipette.py"]
