"""Questions about using the planner or unsupported tool facts are not venue searches."""

import re


def guidance(text):
    if re.search(
        r"^\s*(?:(?:그럼|처음인데)\s*)?(?:(?:뭐|무엇|뭘|어떻게)(?:부터)?\s*(?:시작|알려주|입력)"
        r"|(?:어떤|무슨)\s*(?:정보|조건)(?:를|을|이|가)?\s*(?:필요|알려|입력))",
        text,
    ):
        return (
            "날짜와 지역, 하고 싶은 활동부터 알려주세요. "
            "예산·이동수단은 선택이고, 날짜가 미정이면 장소 후보부터 찾을 수 있어요."
        )
    if not re.search(
        r"찾|검색|추천|바꿔|바꾸|변경|수정|제목|(?:코스|플랜).*(?:짜|만들)", text
    ) and re.search(
        r"영업\s*(?:중|시간|하|해)|운영\s*(?:중|시간)|평점|리뷰\s*수|실제\s*이동시간", text
    ):
        return (
            "현재 도구로 영업 상태·시간, 평점이나 실제 이동시간은 확인할 수 없어요. "
            "장소의 지도 링크에서 확인해 주세요."
        )
    return ""
