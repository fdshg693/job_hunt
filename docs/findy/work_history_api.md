# Findy 職歴・プロジェクト GraphQL API 仕様書

本ドキュメントは、Findyの「キャリア・スキル」画面（`/me/career-skills`）における職歴（`workHistories`）およびプロジェクト（`workHistoryProjects`）の CRUD（作成・更新・削除）に関する GraphQL API 通信仕様のリファレンスです。

---

## 1. 通信プロトコル & 認証仕様

| 項目 | 内容 |
|---|---|
| **エンドポイント** | `https://api.findy-code.io/graphql/user?opname=<OperationName>` |
| **HTTPメソッド** | `POST` |
| **認証方式** | Cookie 認証（セッション Cookie がブラウザに保持されている前提） |
| **必須リクエストヘッダー** | - `Content-Type: application/json`<br>- `Accept: */*`<br>- `x-requested-with: XMLHttpRequest`（※未設定の場合 200 OK で `errors: [{ message: "forbidden" }]` が返る） |
| **推奨実行環境** | Playwright のブラウザコンテキスト内（`page.evaluate` / `fetch`）。セッション Cookie が自動付与されるため最も堅牢。 |

---

## 2. マスタデータ定義

### 2.1 雇用形態 (`allEmploymentPatterns`)

| ID | 名称 |
|---|---|
| 1 | 正社員 |
| 2 | 契約社員 |
| 3 | 派遣社員 |
| 4 | パート・アルバイト |
| 5 | 業務委託 |
| 6 | その他 |

### 2.2 役職区分 (`allPositionTypes`)

| ID (文字列) | 名称 |
|---|---|
| `staff` | メンバー |
| `leader` | リーダー |
| `manager` | マネージャー |

### 2.3 チーム規模区分 (`allTeamScaleTypes`)

| ID (文字列) | 名称 |
|---|---|
| `one_ten` | 1-10人 |
| `ten_fifty` | 10-50人 |
| `fifty_hundred` | 50-100人 |
| `more_hundred` | 100人以上 |

### 2.4 マスタ取得・スキル検索クエリ

```graphql
# マスタ一覧取得
query FetchMasters {
  allEmploymentPatterns {
    id
    name
  }
  allPositionTypes {
    id
    name
  }
  allTeamScaleTypes {
    id
    name
  }
  allJobRoles {
    id
    name
    identifier
    jobRoleCategoryId
    jobRoleCategory {
      id
      name
      identifier
      isManagement
    }
    position
  }
}

# スキル検索（例: "Python"）
query FetchAllSearchSkills($query: String!) {
  allSearchSkills(query: $query) {
    id
    name
  }
}
```

---

## 3. 職歴（所属企業: WorkHistory）API

### 3.1 職歴作成 (`CreateCareerSkillsWorkHistory`)

- **OperationName**: `CreateCareerSkillsWorkHistory`
- **Query**:
```graphql
mutation CreateCareerSkillsWorkHistory($input: CreateWorkHistoryInput!) {
  createWorkHistory(input: $input) {
    clientMutationId
  }
}
```
- **Variables**:
```json
{
  "input": {
    "companyName": "株式会社テスト企業",
    "employmentPatternId": 1,
    "startedOnYear": 2024,
    "startedOnMonth": 4,
    "endedOnYear": null,
    "endedOnMonth": null,
    "isCurrentlyWorking": true
  }
}
```
※退職済みの場合は `isCurrentlyWorking: false` とし、`endedOnYear`, `endedOnMonth` に数値を指定。

### 3.2 職歴更新 (`UpdateCareerSkillsWorkHistory`)

- **OperationName**: `UpdateCareerSkillsWorkHistory`
- **Query**:
```graphql
mutation UpdateCareerSkillsWorkHistory($input: UpdateWorkHistoryInput!) {
  updateWorkHistory(input: $input) {
    clientMutationId
  }
}
```
- **Variables**:
```json
{
  "input": {
    "id": 81518,
    "companyName": "株式会社テスト企業（更新後）",
    "employmentPatternId": 1,
    "startedOnYear": 2024,
    "startedOnMonth": 4,
    "endedOnYear": 2025,
    "endedOnMonth": 3,
    "isCurrentlyWorking": false
  }
}
```

### 3.3 職歴削除 (`DeleteCareerSkillsWorkHistory`)

- **OperationName**: `DeleteCareerSkillsWorkHistory`
- **Query**:
```graphql
mutation DeleteCareerSkillsWorkHistory($input: DeleteWorkHistoryInput!) {
  deleteWorkHistory(input: $input) {
    success
  }
}
```
- **Variables**:
```json
{
  "input": {
    "id": 81518
  }
}
```

---

## 4. プロジェクト（WorkHistoryProject）API

### 4.1 プロジェクト作成 (`CreateCareerSkillsWorkHistoryProject`)

- **OperationName**: `CreateCareerSkillsWorkHistoryProject`
- **Query**:
```graphql
mutation CreateCareerSkillsWorkHistoryProject($input: CreateWorkHistoryProjectInput!) {
  createWorkHistoryProject(input: $input) {
    clientMutationId
  }
}
```
- **Variables**:
```json
{
  "input": {
    "usersWorkHistoryId": 81518,
    "name": "新規開発プロジェクト",
    "detail": "業務詳細テキスト...\n・課題\n・担当範囲\n・成果",
    "startedOnYear": 2024,
    "startedOnMonth": 4,
    "endedOnYear": null,
    "endedOnMonth": null,
    "isCurrentlyWorking": true,
    "jobRoleIds": [7],
    "positionType": "staff",
    "teamScaleType": "one_ten",
    "skillIds": [5, 81, 1506]
  }
}
```
> [!IMPORTANT]
> - 親職歴IDの指定フィールド名は **`usersWorkHistoryId`**（複数形の `users`）です。
> - **業務詳細（`detail`）は50文字以上必須**です（49文字以下の場合 `GraphQL Error: detail must be present and at least 50 characters` となり拒否されます）。
> - `UpdateWorkHistoryProjectInput` では `detail` および `isCurrentlyWorking` が Non-Null 必須です。そのため部分更新時は既存レコードの値でマージしてリクエストする必要があります。

### 4.2 プロジェクト更新 (`UpdateCareerSkillsWorkHistoryProject`)

- **OperationName**: `UpdateCareerSkillsWorkHistoryProject`
- **Query**:
```graphql
mutation UpdateCareerSkillsWorkHistoryProject($input: UpdateWorkHistoryProjectInput!) {
  updateWorkHistoryProject(input: $input) {
    clientMutationId
  }
}
```
- **Variables**:
```json
{
  "input": {
    "id": 126757,
    "name": "更新後プロジェクト名",
    "detail": "更新された業務詳細...",
    "startedOnYear": 2024,
    "startedOnMonth": 4,
    "endedOnYear": 2025,
    "endedOnMonth": 3,
    "isCurrentlyWorking": false,
    "jobRoleIds": [7, 17],
    "positionType": "leader",
    "teamScaleType": "ten_fifty",
    "skillIds": [5, 81, 1506, 167]
  }
}
```

### 4.3 プロジェクト削除 (`DeleteCareerSkillsWorkHistoryProject`)

- **OperationName**: `DeleteCareerSkillsWorkHistoryProject`
- **Query**:
```graphql
mutation DeleteCareerSkillsWorkHistoryProject($input: DeleteWorkHistoryProjectInput!) {
  deleteWorkHistoryProject(input: $input) {
    success
  }
}
```
- **Variables**:
```json
{
  "input": {
    "id": 126757
  }
}
```

---

## 5. キャリア・スキル画面のDOM要素・セレクタ

GraphQL Mutation 失敗時や画面動作確認用の主要セレクタ：

| 要素 | 推奨セレクタ | 備考 |
|---|---|---|
| **職歴追加ボタン** | `button:has-text("職歴を追加")` | 職歴セクション上部 |
| **職歴編集ボタン** | `button[aria-label="${companyName}の職歴を編集"]` | 各職歴カード右上 |
| **プロジェクト追加ボタン** | `button[aria-label="${companyName}のプロジェクトを追加"]` | 職歴カード内下部 |
| **プロジェクトカード** | `div[class*="card"]` | プロジェクト履歴カード |
| **モーダル保存ボタン** | `button[type="submit"]:has-text("保存")` | 入力モーダル内 |
