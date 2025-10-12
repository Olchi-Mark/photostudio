# Photostudio Notes

이 저장소에는 GitHub 원격 저장소가 설정되어 있습니다. 아래 명령으로 원격 구성을 확인할 수 있습니다.

```
$ git remote -v
origin  https://github.com/Olchi-Mark/photostudio.git (fetch)
origin  https://github.com/Olchi-Mark/photostudio.git (push)
```

현재 브랜치(`work`)를 GitHub에 푸시하려면 다음 순서를 따르면 됩니다.

```bash
git push -u origin HEAD
```

이미 한 번 `-u` 옵션으로 추적 관계를 설정했다면, 이후에는 아래와 같이 간단히 푸시할 수 있습니다.

```bash
git push
```

> **주의:** 이 개발 환경에서는 외부 네트워크로의 `git push`가 차단되어 `fatal: unable to access ... CONNECT tunnel failed, response 403` 오류가 발생합니다. 로컬 PC와 같이 네트워크 제약이 없는 환경에서 위 명령을 실행해야 실제로 GitHub에 업로드할 수 있습니다.

원격과 로컬이 동기화되어 있는지 확인하려면 `git status` 명령을 활용하세요.

## GitHub Contents API 업로드 시도

이 환경에서 GitHub Contents API를 호출하여 `main.py`를 직접 업로드하려 했으나, 프록시가 CONNECT 터널을 차단해 아래와 같은 오류가 발생했습니다.

```
HTTP/1.1 403 Forbidden
curl: (56) CONNECT tunnel failed, response 403
```

응답에는 `X-GitHub-Request-Id`나 `X-RateLimit-Remaining` 헤더가 포함되지 않았으며, JSON 본문도 전달되지 않았습니다. 따라서 `sha` 값을 조회할 수 없어 `UNKNOWN` 값을 사용해 다시 한 번 PUT 요청을 보냈지만 동일하게 실패했습니다.

외부 네트워크 차단이 없는 로컬 환경에서 아래 순서를 사용하면 Contents API로 파일을 업데이트할 수 있습니다.

1. `GET /repos/Olchi-Mark/photostudio/contents/main.py?ref=main`으로 최신 `sha`를 조회합니다.
2. 수정한 파일 내용을 Base64로 인코딩합니다.
3. `PUT /repos/Olchi-Mark/photostudio/contents/main.py`에 `message`, `content`, `branch`, `sha`를 포함하여 업로드합니다.

API 호출 시에는 GitHub Personal Access Token을 `Authorization: Bearer <TOKEN>` 헤더로 전달해야 하며, `Accept: application/vnd.github+json` 헤더를 함께 지정하는 것이 좋습니다.
