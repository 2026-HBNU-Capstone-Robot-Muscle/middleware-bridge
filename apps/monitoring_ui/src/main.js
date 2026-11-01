const stateBadge = document.querySelector('#connection-state');
const detail = document.querySelector('#connection-detail');
const connectButton = document.querySelector('#connect-button');
const eventLog = document.querySelector('#event-log');
const topicMessages = document.querySelector('#topic-messages');
const serviceResult = document.querySelector('#service-result');

let socket = null;
let subscribedTopic = null;
let requestNumber = 0;
const pendingServices = new Map();

function log(message) {
  const row = document.createElement('li');
  const time = document.createElement('time');
  const text = document.createElement('code');
  time.textContent = new Date().toLocaleTimeString('ko-KR', { hour12: false });
  text.textContent = message;
  row.append(time, text);
  eventLog.prepend(row);
  while (eventLog.children.length > 80) eventLog.lastElementChild.remove();
}

function setConnection(state, label, message) {
  stateBadge.dataset.state = state;
  stateBadge.textContent = label;
  detail.textContent = message;
  const connected = state === 'online';
  for (const selector of ['#subscribe-form button', '#publish-button', '#service-form button']) {
    document.querySelector(selector).disabled = !connected;
  }
  connectButton.textContent = connected ? '연결 해제' : '연결';
}

function send(payload) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error('rosbridge에 연결되어 있지 않습니다.');
  }
  socket.send(JSON.stringify(payload));
  log(`전송 ${JSON.stringify(payload)}`);
}

function connect(url) {
  if (socket && socket.readyState < WebSocket.CLOSING) {
    socket.close(1000, '사용자 연결 해제');
  }

  setConnection('connecting', '연결 중', `${url}에 연결하고 있습니다.`);
  log(`${url} 연결 시도`);
  socket = new WebSocket(url);

  socket.addEventListener('open', () => {
    setConnection('online', '연결됨', `${url}에 연결되었습니다.`);
    log('WebSocket 연결 완료');
  });

  socket.addEventListener('message', ({ data }) => {
    let message;
    try {
      message = JSON.parse(data);
    } catch {
      log(`해석할 수 없는 응답: ${String(data)}`);
      return;
    }

    if (message.op === 'publish' && message.topic === subscribedTopic) {
      const empty = topicMessages.querySelector('.empty-state');
      if (empty) empty.remove();
      const item = document.createElement('div');
      item.className = 'message-item';
      item.textContent = JSON.stringify(message.msg);
      topicMessages.prepend(item);
      while (topicMessages.children.length > 30) topicMessages.lastElementChild.remove();
      log(`${message.topic} 수신 ${JSON.stringify(message.msg)}`);
      return;
    }

    if (message.op === 'service_response') {
      const pending = pendingServices.get(message.id);
      if (pending) {
        pendingServices.delete(message.id);
        clearTimeout(pending.timeout);
        if (message.result) {
          serviceResult.dataset.state = 'ok';
          serviceResult.textContent = `${message.service} 응답: ${JSON.stringify(message.values)}`;
          log(`서비스 성공 ${message.service}: ${JSON.stringify(message.values)}`);
        } else {
          serviceResult.dataset.state = 'error';
          serviceResult.textContent = `${message.service} 오류: ${message.values?.message ?? '호출 실패'}`;
          log(`서비스 실패 ${message.service}: ${JSON.stringify(message.values)}`);
        }
      } else {
        log(`서비스 응답 ${JSON.stringify(message)}`);
      }
      return;
    }

    if (message.op === 'status') {
      log(`rosbridge 상태: ${message.msg}`);
      return;
    }
    log(`수신 ${JSON.stringify(message)}`);
  });

  socket.addEventListener('error', () => {
    setConnection('error', '연결 오류', 'WebSocket 연결을 확인할 수 없습니다. rosbridge 실행과 주소를 확인하세요.');
    log('WebSocket 오류');
  });

  socket.addEventListener('close', (event) => {
    if (socket?.readyState === WebSocket.CLOSED) {
      setConnection('offline', '연결 안 됨', `연결이 종료되었습니다. (코드 ${event.code})`);
      log(`WebSocket 종료 (코드 ${event.code})`);
    }
    subscribedTopic = null;
    for (const pending of pendingServices.values()) {
      clearTimeout(pending.timeout);
      pending.reject(new Error('연결이 종료되었습니다.'));
    }
    pendingServices.clear();
  });
}

document.querySelector('#connection-form').addEventListener('submit', (event) => {
  event.preventDefault();
  if (socket && socket.readyState < WebSocket.CLOSING) {
    socket.close(1000, '사용자 연결 해제');
  } else {
    const url = document.querySelector('#ws-url').value.trim();
    if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
      setConnection('error', '주소 오류', '주소는 ws:// 또는 wss://로 시작해야 합니다.');
      return;
    }
    connect(url);
  }
});

document.querySelector('#subscribe-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const topic = document.querySelector('#topic-name').value.trim();
  const type = document.querySelector('#topic-type').value.trim();
  if (!topic || !type) return;
  if (subscribedTopic) {
    send({ op: 'unsubscribe', topic: subscribedTopic });
  }
  subscribedTopic = topic;
  send({ op: 'subscribe', topic, type, throttle_rate: 0, queue_length: 1 });
  log(`${topic} 구독 요청 (${type})`);
});

document.querySelector('#publish-button').addEventListener('click', () => {
  const topic = document.querySelector('#topic-name').value.trim();
  const type = document.querySelector('#topic-type').value.trim();
  const data = document.querySelector('#publish-data').value;
  try {
    send({ op: 'publish', topic, type, msg: { data } });
  } catch (error) {
    log(error.message);
  }
});

document.querySelector('#service-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const service = document.querySelector('#service-name').value.trim();
  const type = document.querySelector('#service-type').value.trim();
  const a = Number(document.querySelector('#service-a').value);
  const b = Number(document.querySelector('#service-b').value);
  const id = `ui-service-${++requestNumber}`;
  serviceResult.dataset.state = 'pending';
  serviceResult.textContent = `${service} 응답 대기 중…`;

  try {
    send({ op: 'call_service', id, service, type, args: { a, b } });
  } catch (error) {
    serviceResult.dataset.state = 'error';
    serviceResult.textContent = error.message;
    return;
  }

  const timeout = setTimeout(() => {
    pendingServices.delete(id);
    serviceResult.dataset.state = 'error';
    serviceResult.textContent = `${service} 응답 시간 초과`;
    log(`서비스 시간 초과 ${service}`);
  }, 10000);
  pendingServices.set(id, { timeout, reject: () => {} });
});

document.querySelector('#clear-log').addEventListener('click', () => {
  eventLog.replaceChildren();
});

for (const selector of ['#subscribe-form button', '#publish-button', '#service-form button']) {
  document.querySelector(selector).disabled = true;
}
