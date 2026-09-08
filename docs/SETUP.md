# 1일 1억 토큰 · 운영 안내

[프로필](https://github.com/SUNGMYEONGGI) 상단에 목표를 표현하는 터미널과 실제 Codex 사용량 잔디를 표시합니다. 공유 대화에서 선택한 터미널 문구, GitHub 잔디의 53주 × 7일 구성, 월·요일·범례와 밝은/어두운 테마를 구현했습니다. 기존 Claude Code 사용량과 GIF는 보존했습니다.

## 현재 구성

```text
이 Linux 컴퓨터의 Codex 로그인
  → 사용자 systemd 타이머: 매시간 07분
  → scripts/sync_usage.py: account/usage/read 조회
  → 공개 Gist: token-activity.json
  → GitHub Actions: 매시간 23분
  → token-assets 브랜치: 밝은/어두운 SVG
  → main 브랜치 README에서 이미지 표시
```

- 소스와 설정은 이 저장소의 `main` 브랜치에 있습니다. 로컬 작업 폴더는 `~/github-readme`입니다.
- Gist 주소와 ID는 [`profile.json`](../profile.json)에 있습니다. 저장소 Actions 변수 `TOKEN_GIST_URL`은 그 안의 `gist_raw_url`과 같습니다.
- 수집기는 기존 `gh` 로그인의 `gist` 권한을 사용합니다. 이 설정을 위해 새 PAT를 발급하거나 기존 인증키를 복사하지 않았습니다. 필요하면 `GH_TOKEN`으로 Gists 쓰기 권한의 별도 인증을 사용할 수 있습니다.
- Actions는 저장소에 기본 제공되는 `GITHUB_TOKEN`의 `contents: write`로 이미지 브랜치만 갱신합니다. 별도 Actions secret은 없습니다.
- `assets/daily-routine.svg`는 고정 목표 배너입니다. 명령이 타이핑되고 문구가 출력된 뒤 커서만 깜빡입니다. 동작 줄이기 설정에서는 완성된 화면이 바로 표시됩니다. `daily_routine.sh`를 실제로 실행하지 않습니다.
- SVG 생성 결과는 `token-assets` 브랜치에서 관리합니다. 로컬 `assets/token-activity-*.svg`는 미리보기용이며 Git 추적 대상에서 제외됩니다.

## 데이터 의미

`100,000,000 / day`는 목표입니다. 실제 사용량은 잔디에만 들어갑니다. 수집 범위는 Codex의 계정 토큰 활동 API가 반환하는 값입니다. 일반 ChatGPT 대화 전체의 토큰 합계라고 해석하지 않습니다.

| 항목 | 처리 방식 |
|---|---|
| 같은 날짜 재조회 | 최신 누적값으로 교체. 더하지 않음. 하향 정정도 반영 |
| 응답에 없는 과거 날짜 | 기존 Gist 기록 유지 |
| 일별 버킷 없음/빈 배열/조회 실패 | 게시 중단. 마지막 정상 Gist와 SVG 보존 |
| 날짜별 누락 | 테두리만 있는 `No data` 셀. 실제 0토큰 셀과 구분 |
| 일별 날짜 | API의 `startDate`를 그대로 보존. 시간대를 추측해 재배정하지 않음 |
| 표시 범위 | 서울 날짜 기준 최근 365일, 일요일 시작 53주 격자. 범위 밖 셀은 비움 |
| 상단 합계 | 표시 범위 안에 실제 기록된 날짜의 합. lifetime과 별도 |
| 색상 | 0 / 1~999만 / 1,000만~2,999만 / 3,000만~9,999만 / 1억 이상 |
| 신선도 | 마지막 성공 조회 시각을 UTC로 표시. 48시간 넘으면 `Sync delayed` |

공개되는 JSON은 스키마 버전, 출처, 갱신 시각, 일별 토큰 수, 허용된 사용량 요약뿐입니다. 대화·세션 파일과 `auth.json`을 읽지 않으며, 계정 인증은 Codex와 GitHub CLI가 처리합니다. 조회 과정에서 모델 추론을 실행하지 않습니다.

## 확인 및 수동 실행

프로젝트 디렉터리에서 실행합니다. Python 3.10 이상과 Codex, GitHub CLI가 필요하며 Python 외부 패키지는 필요 없습니다.

```bash
# 인증 상태 확인 — 인증키 자체는 출력하지 않습니다.
codex login status
gh auth status

# 읽기만 수행
python3 scripts/sync_usage.py probe

# Gist 동기화 후 Actions 실행
python3 scripts/sync_usage.py sync
gh workflow run token-grass.yml --repo SUNGMYEONGGI/SUNGMYEONGGI

# 예약 작업과 최근 실행 확인
systemctl --user list-timers github-token-profile.timer
systemctl --user status github-token-profile.service
journalctl --user -u github-token-profile.service -n 30 --no-pager
gh run list --repo SUNGMYEONGGI/SUNGMYEONGGI --workflow token-grass.yml --limit 5
```

로컬 수집은 이 컴퓨터와 사용자 서비스가 실행 중이어야 합니다. 꺼져 있으면 Gist 갱신이 멈춥니다. 타이머의 `Persistent=true`는 다음 서비스 시작 때 놓친 실행을 한 번 처리합니다. 로그인 없이도 사용자 서비스를 유지하려면 해당 시스템에서 `loginctl enable-linger` 지원과 권한이 필요합니다. GitHub Actions 예약 실행과 GitHub 이미지 캐시는 갱신을 지연시킬 수 있습니다.

Codex 확장 버전이 바뀌면 수집기는 PATH의 Codex 또는 최신 VS Code Remote 확장 바이너리를 찾습니다. 다른 위치는 `TOKEN_PROFILE_CODEX`로 지정할 수 있습니다. 토큰 활동 메서드가 없어지거나 로그인 세션이 만료되면 수집 로그를 확인하고 Codex를 갱신하거나 다시 로그인합니다.

## 디자인 수정

```bash
python3 scripts/sync_usage.py probe --output .local/preview-data.json
python3 scripts/render_profile.py --input .local/preview-data.json
```

브라우저에서 [`preview.html`](../preview.html)을 열면 테마를 전환하며 확인할 수 있습니다. 터미널은 [`assets/daily-routine.svg`](../assets/daily-routine.svg), 잔디는 [`scripts/render_profile.py`](../scripts/render_profile.py)를 수정합니다. README의 기존 Claude 섹션 마커는 그대로 유지합니다.

```bash
# 타이머 재설치 / 제거
python3 scripts/install_timer.py install
python3 scripts/install_timer.py uninstall
```

프로젝트를 다른 경로로 옮겼다면 타이머를 재설치합니다. 새 컴퓨터에서는 본인의 Codex와 GitHub에 로그인한 뒤 설치합니다. 같은 Gist를 여러 컴퓨터가 동시에 쓰도록 설정하지 마세요. 로컬 잠금은 이 컴퓨터 안의 중복 실행만 방지합니다.

## 참고

- [공유 대화](https://chatgpt.com/share/6aa019ea-470c-83ee-99eb-a156c34614dc)
- [공식 Codex app-server 문서: 계정 토큰 사용량](https://learn.chatgpt.com/docs/app-server#7-token-usage-chatgpt)
- 설치된 Codex CLI 0.153.0에서 생성한 실험적 프로토콜 스키마와 실제 조회로 `account/usage/read` 응답을 확인했습니다.
