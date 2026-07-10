# DreamJar — Google Apps Script 백엔드

## 배포 순서

### 1단계: Spreadsheet ID 설정

`Code.gs` 상단의 `SPREADSHEET_ID` 값을 실제 Google Spreadsheet ID로 교체합니다.

```js
var SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID_HERE';
// ↓ 이렇게 교체
var SPREADSHEET_ID = '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms';
```

> Spreadsheet ID는 URL에서 확인합니다:
> `https://docs.google.com/spreadsheets/d/[여기가 ID]/edit`

---

### 2단계: 코드 붙여넣기

1. [Google Apps Script](https://script.google.com) 접속
2. **새 프로젝트** 생성 (이름: `DreamJar`)
3. 기본 생성된 `Code.gs` 내용을 모두 삭제
4. 이 리포의 `apps/dreamjar/Code.gs` 내용을 전체 붙여넣기
5. 💾 저장 (Ctrl+S)

---

### 3단계: 시트 초기화 (1회만)

1. Apps Script 에디터 상단 함수 선택 드롭다운에서 **`initSheets`** 선택
2. **▶ 실행** 클릭
3. 권한 요청 팝업이 뜨면 **"고급" → "안전하지 않은 페이지로 이동"** 클릭 후 허용
4. 실행 로그에 `initSheets 완료` 확인

이 단계가 완료되면 Spreadsheet에 아래 7개 시트가 생성됩니다:

| 시트 이름 | 설명 |
|-----------|------|
| `users` | 사용자 |
| `jars` | Jar(저금통) |
| `jar_members` | Jar 참여 멤버 |
| `entries` | 리워드 적립 내역 |
| `donation_out` | 기부 발신 내역 |
| `donation_in` | 기부 수신 내역 |
| `controls` | Control 목록 |

---

### 4단계: Web App 배포

1. Apps Script 에디터 우측 상단 **"배포"** → **"새 배포"** 클릭
2. 유형: **웹 앱**
3. 설정:
   - **실행 대상**: 나(내 Google 계정)
   - **액세스 권한**: 모든 사용자 (또는 테스트 중이면 "자신만")
4. **배포** 클릭
5. 생성된 **웹 앱 URL** 복사 → 프론트엔드 `WEB_APP_URL` 에 붙여넣기

> ⚠️ 코드를 수정할 때마다 **"배포" → "배포 관리" → "새 버전으로 업데이트"** 를 해야 변경 사항이 반영됩니다.

---

## API 레퍼런스

### POST (doPost)

`Content-Type: application/json` 으로 요청합니다.

#### `registerUser`
```json
{ "action": "registerUser", "name": "홍길동", "email": "hong@example.com" }
```
응답: `{ "ok": true, "data": { "userId": "u_..." } }`

#### `createJar`
```json
{ "action": "createJar", "name": "여행 적금", "description": "2026 유럽 여행", "ownerId": "u_..." }
```
응답: `{ "ok": true, "data": { "jarId": "jar_..." } }`

#### `joinJar`
```json
{ "action": "joinJar", "jarId": "jar_...", "userId": "u_..." }
```
응답: `{ "ok": true, "data": { "memberId": "m_..." } }`

#### `setControl`
```json
{ "action": "setControl", "memberId": "m_...", "controlId": "ctrl_..." }
```
응답: `{ "ok": true, "data": { "updated": true } }`

#### `createControl`
```json
{ "action": "createControl", "name": "기본 제어", "ownerId": "admin", "type": "default" }
```
응답: `{ "ok": true, "data": { "controlId": "ctrl_..." } }`

#### `addEntry`
```json
{ "action": "addEntry", "jarId": "jar_...", "userId": "u_...", "amount": 5000, "note": "운동 완료" }
```
응답: `{ "ok": true, "data": { "entryId": "ent_..." } }`

#### `donate` (너구리 수수료)
```json
{ "action": "donate", "fromJarId": "jar_A", "toJarId": "jar_B", "amount": 10000 }
```
응답:
```json
{
  "ok": true,
  "data": {
    "donationId": "don_...",
    "feeRate": 0.234,
    "feeAmount": 2340,
    "netAmount": 7660
  }
}
```
> 수수료율은 서버사이드에서 `Math.random() * 0.5` (0~50%)로 결정됩니다.

---

### GET (doGet)

URL 쿼리 파라미터로 전달합니다.

#### `getJarsByUser`
```
GET ?query=getJarsByUser&userId=u_...
```

#### `getEntries`
```
GET ?query=getEntries&jarId=jar_...
```

#### `getAdminControls`
```
GET ?query=getAdminControls
```

#### `getJar`
```
GET ?query=getJar&jarId=jar_...
```
응답에 `currentAmount`(entries 합계), `entryCount` 포함.

---

## 오류 응답 형식

```json
{ "ok": false, "error": "오류 메시지" }
```
