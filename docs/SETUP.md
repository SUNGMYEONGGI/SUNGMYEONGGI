# 100M Token per day on github · 운영 안내

[프로필](https://github.com/SUNGMYEONGGI)에 목표를 표현하는 터미널과 **Codex + Claude Code 사용량을 합산한 잔디 하나**를 표시합니다. 잔디는 오션 팔레트이며 라이트·다크 테마, 53주 × 7일 격자, 월·요일·범례를 제공합니다.

## 매일 갱신하는 흐름

```text
매일 00:00 (Asia/Seoul, UTC+9) · 이 컴퓨터의 systemd 사용자 타이머
  → Codex: account/usage/read에서 날짜별 사용량 조회
  → Claude Code: 로컬 JSONL의 사용량 필드 수집 및 중복 제거
  → 전날까지 날짜별 합산 → 기존 공개 Gist 갱신
  → GitHub Actions를 1회 호출 → 오션 SVG 두 개 생성
  → token-assets 브랜치에 게시 → README에 표시
```

소스는 `main` 브랜치, 이미지 결과는 `token-assets` 브랜치에 있습니다. 로컬 작업 폴더는 `~/github-readme`입니다. [`profile.json`](../profile.json)에 Gist 주소, 시간대, Claude 데이터 디렉터리가 있고, Actions 변수 `TOKEN_GIST_URL`은 `gist_raw_url` 값입니다.

로컬 갱신에는 기존 `gh` 인증의 gist·workflow 권한을 사용합니다. Actions는 기본 제공되는 `GITHUB_TOKEN`의 `contents: write`로 이미지만 게시합니다. 별도 Actions secret은 없습니다. Actions는 수집 성공 후 `workflow_dispatch`로 호출하며, 독립적인 cron이나 push 트리거는 없습니다. 수집과 실행 대기 때문에 실제 이미지 표시는 00:00보다 조금 늦습니다.

`.local/daily-update.json`은 날짜와 데이터 스키마별 실행 상태입니다. 같은 날 재실행은 건너뛰며, Gist 갱신 뒤 Actions 호출이 실패하면 호출만 재시도합니다. Codex 전용 데이터에서 합산 데이터로 바꿀 때는 새 스키마로 한 번 갱신합니다.

## 날짜별 합산 규칙

```text
days[날짜] = 해당 날짜의 Codex 토큰 + 해당 날짜의 Claude Code 토큰
```

Gist의 `schemaVersion: 2`에는 표시용 `days`와 재계산용 `sources.codex`, `sources.claude` 날짜별 숫자가 들어 있습니다. 화면은 `days` 하나만 사용합니다. 원본 집계를 보관하므로 이미 합산한 값에 다시 Claude 토큰을 더하지 않습니다. 기존 스키마 1의 날짜별 값은 Codex 기록으로 한 번 이관합니다.

| 항목 | 처리 방식 |
|---|---|
| Codex | 로그인 계정의 `account/usage/read` 일별 버킷 |
| Claude Code | 설정한 데이터 디렉터리의 프로젝트·서브에이전트 JSONL에 기록된 사용량 |
| Claude 토큰 공식 | `input_tokens + output_tokens + cache_creation_input_tokens + cache_read_input_tokens` |
| 중복 제거 | 같은 응답의 `message.id`는 한 번만 집계. 스트리밍 중 누적 카운터는 최대 관측값으로 갱신 |
| 이중 합산 방지 | `cache_creation` 세부 내역, `iterations`, `result`의 누적 합계는 다시 더하지 않음 |
| 날짜 | Codex는 API의 `startDate` 유지. Claude는 응답의 최초 기록 시각을 한국 날짜로 변환 |
| 반영 범위 | 전날까지 수집하고, 전날을 끝으로 최근 365일 표시 |
| 재조회 | Codex 일별 스냅샷은 최신 값으로 교체. Claude는 중복 제거된 로컬 집계로 재계산 |
| 누락 | 확인 가능한 소스의 값으로 합산. 두 소스 모두 기록이 없으면 `No data` |
| 요약 | `recordedTokens`는 보관된 날짜 합계, `peakDailyTokens`는 그중 최대값 |
| 색상 구간 | 0 / 1~999만 / 1,000만~2,999만 / 3,000만~9,999만 / 1억 이상 |

Claude의 합계는 **이 컴퓨터에 남아 있는 Claude Code 사용 기록의 범위**입니다. 처음 연동할 때 확인된 기록은 2026-07-28~2026-09-07의 14일치, 145,350,536토큰입니다. 과거에 별도로 만든 Claude Gist의 반올림된 표시 숫자를 일별 원본처럼 환산하지 않습니다. 입력·캐시 토큰을 중복 제거하고, 로컬에 저장된 출력 토큰의 최종 관측값을 사용합니다. 완성된 응답 기록이 없는 경우 출력 토큰은 실제보다 적을 수 있습니다. [공식 사용량·중복 집계 안내](https://code.claude.com/docs/en/agent-sdk/cost-tracking)

Codex의 계정 활동과 Claude의 로컬 로그는 제공 범위와 날짜 기준이 다를 수 있으므로 이 합계를 계정 전체의 과금 수치로 해석하지 않습니다. Codex API는 자정에 전날 집계를 아직 제공하지 않을 수 있습니다. 2026-09-09 00:00 KST에도 최신 기록은 2026-09-07이었으며, 지연된 기록은 이후 일별 조회에서 보완합니다.

## 로컬 사용량 보존

Claude Code의 로그는 자동 정리될 수 있어, 수집된 사용량은 `.local/claude-usage.sqlite3`에 보존합니다. 이 파일에는 **해시 처리된 메시지 식별자, UTC 시각, 토큰 카운터 네 개**만 저장하며, 대화 본문·프로젝트 경로·인증키는 저장하지 않습니다. JSONL을 읽을 때 사용량 외의 내용은 게시하거나 별도 보관하지 않습니다. Gist에는 날짜별 집계 숫자만 올라갑니다. [공식 로그 보관 안내](https://code.claude.com/docs/en/claude-directory#application-data)

`.local/`은 Git 추적 대상에서 제외됩니다. **컴퓨터를 옮길 때 `claude-usage.sqlite3`도 개인 백업으로 옮기세요.** 이 파일을 지워 이전 집계를 재현할 수 없게 되면, 공개된 Claude 기록을 덮어쓰지 않고 갱신을 중단합니다. 프로젝트 로그를 정리한 뒤에도 이미 수집한 기록은 유지됩니다.

`claude_data_dirs`에는 Claude Code 데이터 디렉터리를 추가할 수 있습니다. 기본값은 `["~/.claude"]`입니다. 복사된 동일 메시지는 중복 제거합니다. 읽을 수 없는 디렉터리, 잘못된 사용량 데이터, API 실패가 있으면 기존 Gist와 이미지를 보존합니다.

## 확인 및 수동 실행

Python 3.10 이상, Codex, GitHub CLI를 사용합니다. 별도 Python 패키지는 필요 없습니다.

```bash
# 인증 상태
codex login status
gh auth status

# 합산 데이터 확인 및 로컬 미리보기 — Gist에 게시하지 않음
python3 scripts/sync_usage.py probe --output .local/preview-data.json
python3 scripts/render_profile.py --input .local/preview-data.json

# 하루 1회 수집 → Actions 호출 (이미 실행했으면 건너뜀)
python3 scripts/daily_update.py

# 필요할 때 수동으로 다시 합산·게시
python3 scripts/sync_usage.py sync
gh workflow run token-grass.yml --repo SUNGMYEONGGI/SUNGMYEONGGI

# 예약과 실행 결과
systemctl --user list-timers github-token-profile.timer
systemctl --user status github-token-profile.service
journalctl --user -u github-token-profile.service -n 30 --no-pager
gh run list --repo SUNGMYEONGGI/SUNGMYEONGGI --workflow token-grass.yml --limit 5
```

수집하려면 이 컴퓨터와 사용자 서비스가 실행 중이어야 합니다. `Persistent=true`는 다음 서비스 시작 때 놓친 예약을 한 번 처리합니다. 로그인 없이 사용자 서비스를 유지하려면 해당 시스템의 `loginctl enable-linger` 지원과 권한이 필요합니다. 마지막 성공 조회가 48시간을 넘으면 잔디에 `Sync delayed`가 표시됩니다.

```bash
python3 scripts/install_timer.py install
python3 scripts/install_timer.py uninstall
```

프로젝트를 옮겼다면 타이머를 재설치합니다. 같은 Gist를 여러 컴퓨터에서 동시에 갱신하지 마세요. 로그를 한 수집 컴퓨터에 모으면 메시지 중복을 제거할 수 있습니다.

## 디자인 수정

[`preview.html`](../preview.html)에서 테마를 전환해 확인할 수 있습니다. 배너는 [`assets/daily-routine.svg`](../assets/daily-routine.svg), 오션 잔디는 [`scripts/render_profile.py`](../scripts/render_profile.py)를 수정합니다. 로컬 `assets/token-activity-*.svg`는 미리보기용이며 Git에는 올라가지 않습니다.

배너의 `100,000,000 / day`는 목표 문구입니다. 실제 합산 사용량은 잔디에 표시합니다. 터미널 출력 후 커서가 깜빡이고, 동작 줄이기 설정에서는 완성된 화면이 바로 표시됩니다.

- [공유 대화](https://chatgpt.com/share/6aa019ea-470c-83ee-99eb-a156c34614dc)
- [공식 Codex 계정 토큰 활동 문서](https://learn.chatgpt.com/docs/app-server#7-token-usage-chatgpt)
