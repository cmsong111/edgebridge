# EdgeBridge

SmartThings Edge 드라이버를 위한 포워딩 브릿지 서버입니다.
[toddaustin07/edgebridge](https://github.com/toddaustin07/edgebridge)를 포크해 Docker로 운영하기 쉽게 정리했습니다.

> 상시 켜 둔 컴퓨터 대신 **Android** 기기에서 돌리는 비슷한 앱도 있습니다. [이 페이지](https://aeb.dothesmartthings.com/)를 참고하세요.

## 무엇을 하나요

SmartThings 허브의 Edge 드라이버는 **같은 LAN 안의 IP에만** 통신할 수 있고, 고정 포트도 쓸 수 없습니다. EdgeBridge는 LAN에 상시 떠 있으면서 이 두 가지 제약을 풀어 줍니다.

1. **Edge 드라이버의 요청을 외부로 전달합니다.**
   드라이버가 EdgeBridge에 요청을 보내면 EdgeBridge가 인터넷의 URL로 대신 보내고 응답을 돌려줍니다.
   SmartThings API(`api.smartthings.com`)로 가는 요청에는 설정한 토큰을 자동으로 붙여, 드라이버가 다른 SmartThings 기기 상태를 읽는 등 SmartApp 같은 동작을 할 수 있습니다.
2. **LAN 기기·앱의 메시지를 Edge 드라이버로 전달합니다.**
   드라이버가 "이 IP에서 오는 메시지를 받고 싶다"고 EdgeBridge에 등록해 두면, 그 기기가 EdgeBridge로 보낸 HTTP 요청이 허브의 해당 드라이버로 전달됩니다. 드라이버 포트가 바뀌어도 드라이버가 다시 등록하면 되므로 기기 쪽 설정은 바꿀 필요가 없습니다. (기기에는 고정 IP를 권장합니다.)

## Docker로 실행하기

준비물:

- Docker와 Docker Compose가 설치된, LAN에 상시 켜져 있는 서버 (Linux 권장)
- SmartThings API를 쓸 경우 [Personal Access Token](https://account.smartthings.com/tokens)

### 1. 소스 받기

```sh
git clone <이 저장소 URL> edgebridge
cd edgebridge
```

### 2. 설정 파일 만들기

```sh
cp .env.example .env
```

`.env`를 열어 필요한 값만 채웁니다. 보통은 아래 두 개만 보면 됩니다.

```ini
SMARTTHINGS_TOKEN=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
HOST_PORT=8088
```

`.env`는 `.gitignore`와 `.dockerignore`에 들어 있어 GitHub에도, Docker 이미지에도 들어가지 않습니다. 전체 항목은 [설정](#설정-env)을 참고하세요.

### 3. 실행

```sh
docker compose up -d --build
```

### 4. 동작 확인

```sh
docker compose ps                 # edgebridge 컨테이너 하나가 Up 상태인지 확인
docker compose logs -f            # 로그 보기 (Ctrl+C로 빠져나옴)

# 200이 나오면 정상
curl -X POST -o /dev/null -w '%{http_code}\n' http://<서버IP>:8088/api/ping

# 토큰을 설정했다면 SmartThings 기기 목록이 JSON으로 나옴
curl "http://<서버IP>:8088/api/forward?url=https://api.smartthings.com/v1/devices"
```

`8088` 대신 `.env`의 `HOST_PORT` 값을 쓰세요.

### 5. Edge 드라이버에 주소 입력

SmartThings 앱에서 EdgeBridge를 쓰는 기기의 설정에 들어가 브릿지 주소를 `<서버IP>:<HOST_PORT>`로 입력합니다.

### 운영 명령어

| 하고 싶은 일 | 명령어 |
| --- | --- |
| 로그 보기 | `docker compose logs -f` |
| 재시작 | `docker compose restart` |
| `.env` 수정 후 반영 | `docker compose up -d` |
| 코드 업데이트 | `git pull && docker compose up -d --build` |
| 중지 | `docker compose down` |
| 중지하고 등록 정보까지 삭제 | `docker compose down -v` |

- 드라이버 등록 정보(`.registrations`)는 `edgebridge-data` 볼륨에 저장되므로 컨테이너를 다시 만들어도 유지됩니다.
- 컨테이너는 `restart: unless-stopped`로 설정되어 있어 서버가 재부팅되면 자동으로 다시 뜹니다.

### 주의: 등록 기능은 출발지 IP로 기기를 구분합니다

LAN 기기에서 온 메시지를 드라이버로 넘길 때 EdgeBridge는 **요청을 보낸 IP**를 보고 어느 드라이버로 보낼지 정합니다.

- **Linux 서버의 Docker**는 원래 출발지 IP를 그대로 넘겨주므로 문제없습니다.
- **Docker Desktop(Mac/Windows)**은 출발지 IP가 Docker 내부 게이트웨이 IP로 바뀌어 기기를 구분하지 못합니다. 등록 기능을 쓰려면 Linux 서버에서 실행하거나 [Docker 없이 실행](#docker-없이-실행하기)하세요.

외부로 요청을 전달하는 기능(`/api/forward`)은 어디서 실행해도 상관없습니다.

## 설정 (.env)

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `SERVER_IP` | (비움) | 서버가 요청을 받을 IP. 비우면 모든 인터페이스에서 받습니다. **Docker에서는 비워 두세요.** |
| `SERVER_PORT` | `8088` | 서버 포트. Docker에서는 컨테이너 안쪽 포트입니다. |
| `SMARTTHINGS_TOKEN` | (없음) | SmartThings Personal Access Token. `api.smartthings.com`으로 가는 요청에만 붙고, 드라이버가 직접 `Authorization` 헤더를 보내면 그것을 우선합니다. |
| `FORWARDING_TIMEOUT` | `5` | 외부 요청과 허브 전달의 타임아웃(초) |
| `CONSOLE_OUTPUT` | `yes` | 콘솔에 로그 출력 |
| `LOGFILE_OUTPUT` | `no` | 파일에 로그 기록. 시작할 때마다 기존 파일을 지우고 새로 씁니다. |
| `LOGFILE` | `edgebridge.log` | 로그 파일 경로. Docker에서는 `/app/data` 기준입니다. |
| `DEBUG` | `no` | 디버그 메시지 출력 (전달한 요청의 헤더·본문·응답까지 보여 줌). 실행 옵션 `-d`와 같습니다. |
| `HOST_PORT` | `8088` | (Docker 전용) 호스트에 노출할 포트 |
| `TZ` | `Asia/Seoul` | (Docker 전용) 로그 시각에 쓸 시간대 |

- yes/no 항목은 `true`/`false`, `on`/`off`, `1`/`0`도 받습니다.
- 값에 주석을 같은 줄에 붙이지 마세요. 주석은 `#`로 시작하는 별도 줄에 씁니다.
- 잘못된 값은 시작할 때 경고를 남기고 기본값을 씁니다.

## Docker 없이 실행하기

Python 3.10 이상이 필요합니다.

```sh
pip3 install -r requirements.txt
cp .env.example .env              # 값 채우기
python3 edgebridge.py             # 디버그 메시지까지 보려면: python3 edgebridge.py -d
```

`.env`와 `.registrations`는 **현재 작업 디렉터리**에서 읽고 씁니다. 환경 변수로 직접 넘긴 값은 `.env`보다 우선합니다.

### 부팅 시 자동 실행 (systemd)

`/etc/systemd/system/edgebridge.service`를 만들고 `<경로>`를 EdgeBridge 폴더로 바꿉니다.

```ini
[Unit]
Description=edgebridge application
After=network.target

[Service]
ExecStart=/usr/bin/python3 <경로>/edgebridge.py
WorkingDirectory=<경로>
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now edgebridge
sudo systemctl status edgebridge
```

백그라운드로 돌릴 때는 `CONSOLE_OUTPUT=no`, `LOGFILE_OUTPUT=yes`로 두고 `tail -f edgebridge.log`로 로그를 보는 것을 권장합니다. 디버그 모드에서는 로그 파일이 빠르게 커지니 필요할 때만 켜세요.

## 서버 모니터링 (선택)

[이 채널](https://bestow-regional.api.smartthings.com/invite/Q1jP7BqnNNlL)에서 **EdgeBridge Monitor V1** 드라이버를 설치하면 EdgeBridge가 응답하지 않을 때 알림을 받을 수 있습니다.

1. 허브를 채널에 등록하고 드라이버를 설치합니다.
2. SmartThings 앱에서 *기기 추가 → 주변 기기 검색*을 하면 'Edgebridge Monitor' 기기가 생깁니다.
3. 기기 설정에서 브릿지 주소와 확인 주기(초)를 입력합니다.

기기는 주기적으로 EdgeBridge에 핑을 보내고 'online'/'offline'을 표시합니다. 응답이 없으면 5초 간격으로 두 번 더 시도한 뒤 offline으로 바꿉니다. 허브 재부팅 직후처럼 요청이 몰리면 잠깐 offline으로 보일 수 있지만 30초 정도면 돌아옵니다. 'offline'일 때 알림을 보내는 자동화 루틴을 만들어 두면 좋습니다.

## 활용 사례

원작자가 EdgeBridge와 함께 쓰도록 만든 Edge 드라이버가 있습니다. [공유 채널](https://bestow-regional.api.smartthings.com/invite/d429RZv8m9lo)에서 설치할 수 있습니다.

- LAN Device Trigger V2b (여러 트리거를 기기 하나에 담은 버전도 있음)
- LAN Motion Device Driver
- LAN Presence Device Driver V1
- LAN Contact Device Driver V1
- LAN Temp-Humidity Driver V1

LAN의 기기나 앱이 EdgeBridge로 HTTP 요청을 보내면, 등록된 위 드라이버의 기기 상태가 바뀝니다. 그 밖의 예시는 다음과 같습니다.

| 사례 | 설명 |
| --- | --- |
| 날씨 기기 | 인터넷 날씨 API에서 현재 날씨와 예보를 가져옵니다 (외부 전달 기능). |
| [PurpleAir](https://github.com/toddaustin07/PurpleAir) | PurpleAir API로 대기질 지수를 가져옵니다 (외부 전달 기능). |
| [Online Status Monitor](https://github.com/toddaustin07/onlinestatusmon) | SmartThings API로 다른 기기의 온라인 상태를 확인합니다 (토큰 사용). |
| [Web Requestor](https://github.com/toddaustin07/webrequestor) | 자동화에서 임의의 웹 요청을 보냅니다 (외부 전달 기능). |
| Shelly 모션 센서 | 모션 감지 시 EdgeBridge로 HTTP 메시지를 보내 [LAN 모션 드라이버](https://github.com/toddaustin07/lanmotion)로 전달합니다. 지금은 Gen 1 Shelly 전용 드라이버도 있습니다. |
| Blue Iris 카메라 | 모션 감지 액션의 웹 요청을 EdgeBridge로 보내 클라우드 없이 로컬에서 처리합니다. Blue Iris와 같은 컴퓨터에서 EdgeBridge를 돌려도 됩니다. |
| [휴대폰 재실 감지](https://github.com/toddaustin07/phonepresence) | LAN에 휴대폰이 있는지 감지해 LAN Presence 드라이버로 알립니다. |
| [Ping Tracker](https://github.com/toddaustin07/PingTracker) | 지정한 IP에 핑을 보내 응답 여부를 Presence 드라이버로 알립니다. |
| [LAN Trigger](https://github.com/toddaustin07/lantrigger) | HTTP 요청을 보낼 수 있는 LAN 기기라면 무엇이든 SmartThings 버튼을 눌러 자동화를 실행할 수 있습니다. |

## 인터페이스 명세

Edge 드라이버를 직접 만들거나 Web Requestor URL을 설정하는 분을 위한 내용입니다. 아래 예시는 EdgeBridge가 `192.168.1.140:8088`에 있다고 가정합니다.

### 외부로 요청 전달

드라이버가 LAN 밖으로 HTTP 요청을 보내고 싶을 때 씁니다. `GET`, `POST`, `PUT`을 지원하며, 요청 본문과 헤더도 함께 전달됩니다.

```
[GET | POST | PUT] http://192.168.1.140:8088/api/forward?url=<URL>
```

`<URL>`은 쿼리 파라미터를 포함한 `http`/`https` 주소면 무엇이든 됩니다.

```
POST http://192.168.1.140:8088/api/forward?url=https://http-bin.org/post?key1=key1value&key2=key2value
PUT  http://192.168.1.140:8088/api/forward?url=https://www.somesite.com/update?key1=key1value&key2=key2value
GET  http://192.168.1.140:8088/api/forward?url=https://api.smartthings.com/v1/devices/80e99446-a656-41e2-9db7-3981f7c0e126/components/main/capabilities/switch/status
GET  http://192.168.1.140:8088/api/forward?url=https://api.wheretheiss.at/v1/satellites/25544
```

| 응답 | 의미 |
| --- | --- |
| `200` | 성공. 대상 서버의 응답 본문을 그대로 돌려줍니다. |
| 대상 서버의 상태 코드 | 대상 서버가 200이 아닌 코드를 준 경우 (본문 없음) |
| `400` | `url=`이 없거나 올바른 http/https URL이 아님 |
| `405` | 지원하지 않는 메서드 (예: `DELETE`) |
| `502` | 대상 서버에 연결하지 못했거나 타임아웃 |

### LAN 기기 메시지를 드라이버로 전달

드라이버가 특정 LAN 기기·앱에서 오는 메시지를 받고 싶을 때, 먼저 EdgeBridge에 **등록**합니다.

```
POST   http://192.168.1.140:8088/api/register?devaddr=<기기 주소>&hubaddr=<허브IP:포트>&edgeid=<device.id>
DELETE http://192.168.1.140:8088/api/register?devaddr=<기기 주소>&hubaddr=<허브IP:포트>&edgeid=<device.id>
```

| 파라미터 | 형식 | 예시 |
| --- | --- | --- |
| `devaddr` | 메시지를 보낼 기기의 IP. 포트는 선택 | `192.168.1.150`, `192.168.1.140:2345` |
| `hubaddr` | 드라이버가 쓰는 허브 IP와 포트. **포트 필수** | `192.168.1.107:31732` |
| `edgeid` | 드라이버의 `device.id` (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) | `3894BE52-09E8-4CFD-AD5C-580DE59B6873` |

```
POST http://192.168.1.140:8088/api/register?devaddr=192.168.1.150&hubaddr=192.168.1.107:31732&edgeid=3894BE52-09E8-4CFD-AD5C-580DE59B6873
```

같은 `devaddr`와 `edgeid`로 다시 등록하면 기존 등록을 덮어씁니다. 파라미터가 빠지거나 형식이 틀리면 `400`, 등록되지 않은 항목을 지우려 하면 `404`를 돌려줍니다.

등록이 끝나면 기기는 GET이나 POST 요청을 EdgeBridge로 보내기만 하면 됩니다. 출발지 IP(와 등록한 경우 포트)가 등록 정보와 맞으면 EdgeBridge가 요청을 허브의 드라이버로 넘깁니다. 기기는 허브 IP나 드라이버 포트를 몰라도 됩니다.

```
POST http://192.168.1.140:8088/<드라이버가 정한 경로>     예: /mydevice/presence/present
```

### 등록 정보와 자동 정리

등록 정보는 `.registrations` 파일에 저장되어 재시작해도 유지됩니다. 드라이버나 기기가 등록 해제 없이 삭제되면 쓸모없는 등록이 남을 수 있는데, 같은 허브 주소로 전달이 3번 실패하면 EdgeBridge가 해당 등록을 자동으로 지우고 로그에 남깁니다. 정상 동작입니다.

### 핑

`POST /api/ping`은 아무 처리 없이 `200`을 돌려줍니다. 모니터링 용도로 쓰며 로그에도 남지 않습니다 (디버그 모드 제외).

## 원본과 달라진 점

- 설정 파일 `edgebridge.cfg` 대신 `.env`(환경 변수)를 씁니다. 키 이름은 `Server_Port` → `SERVER_PORT`처럼 대문자로 바뀌었습니다.
- `Dockerfile`과 `docker-compose.yml`을 저장소 최상단으로 옮겨, 파일을 복사하지 않고 바로 빌드할 수 있습니다.
- `.cfg`를 읽던 미리 빌드한 실행 파일(Windows `.exe`, Raspberry Pi용)은 제거했습니다. Python 스크립트나 Docker로 실행하세요.
- 잘못된 요청이 들어와도 처리 중 오류로 끊기지 않고 `400`/`404`/`405`/`502`로 응답합니다.
- 재시작 후 같은 기기를 다시 등록하면 중복 등록되던 문제와, `FORWARDING_TIMEOUT` 설정이 적용되지 않던 문제를 고쳤습니다.
- SmartThings 토큰은 실제 `api.smartthings.com` 호스트로 가는 요청에만 붙습니다.

## 라이선스

[Apache License 2.0](LICENSE). 원저작자 Todd Austin.
