"""Location replies resume a task; selections never turn into automatic private reads."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from dialogue_evaluation import MemoryStore
from semantic_fixture import semantic_response

from we2day_api import ai_planner
from we2day_api.ai_place_policy import explicit_area
from we2day_api.ai_runtime import Budget, RunStats
from we2day_api.places import SearchResults


class LocationFlow:
    def __init__(self, monkeypatch, target="고깃집", destination="서울특별시 중랑구 신내동 1"):
        self.store = MemoryStore({"initial": {}})
        self.history, self.reads, self.model_inputs = [], [], []
        self.id, self.place_id = str(uuid4()), str(uuid4())
        self.target, self.destination = target, destination
        self.omit_area = False
        flow = self

        class IO:
            def __init__(self, *args):
                pass

            async def perform(self, action):
                flow.reads.append(action)
                if action[0] == "data":
                    assert action[1] == "favorite_places"
                    assert action[2]["id"] == f"in.({flow.place_id})"
                    return [{"id": flow.place_id, "label": "샘플 집", "destination": destination}]
                assert action[0] == "places"
                area = "성수동" if "성수동" in action[1] else "신내동"
                district = "성동구" if area == "성수동" else "중랑구"
                return SearchResults.model_validate(
                    {
                        "items": [
                            {
                                "title": "샘플" + flow.target,
                                "category": "음식점>한식"
                                if flow.target != "카페"
                                else "음식점>카페",
                                "roadAddress": f"서울특별시 {district} {area} 2",
                            }
                        ]
                    }
                )

        async def complete(*args, **kwargs):
            pytest.fail("An unresolved location or verified search must not use generic prose")

        monkeypatch.setattr(ai_planner, "ToolIO", IO)
        monkeypatch.setattr(ai_planner, "complete", complete)

    async def send(self, text, selected=False):
        self.history.append({"role": "user", "content": text})
        body = ai_planner.ChatInput.model_validate(
            {
                "messages": self.history[-11:],
                "conversation_id": self.id,
                "request_id": str(uuid4()),
                "version": self.store.version,
                "selected_places": [{"source": "favorite", "id": self.place_id, "usage": "anchor"}]
                if selected
                else [],
            }
        )

        def semantic(request):
            inputs = json.loads(request.content)
            self.model_inputs.append(inputs)
            data = json.loads(inputs["messages"][-1]["content"])
            return semantic_response(
                request,
                {
                    "operation": "search",
                    "area": "" if self.omit_area else explicit_area(data["request"]),
                    "targets": [self.target],
                    "anchor_needed": False,
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(semantic)) as client:
            result = await ai_planner._chat(
                body,
                SimpleNamespace(cloudflare_account_id="a" * 32, cloudflare_api_token="synthetic"),
                self.store,
                client,
                Budget(),
                RunStats("location"),
            )
        self.history.append({"role": "assistant", "content": result.reply})
        return result


@pytest.mark.parametrize("target", ["고깃집", "쌀국수", "공연장"])
@pytest.mark.parametrize("answer", ["성수동", "성수동이야", "지역: 성수동"])
@pytest.mark.parametrize("ending", ["있나?", "있어?", "있어요?"])
def test_natural_question_waits_for_location_then_resumes_original_target(
    monkeypatch, target, answer, ending
):
    async def run():
        c = LocationFlow(monkeypatch, target)
        first = await c.send(f"샘플 집 근처에서 보려고 하는데 주변에 괜찮은 {target}{ending}")
        assert not c.reads and not first.candidates
        assert first.context.location_request["basis"] == c.store.version
        assert first.context.location_request["search"]["targets"][0]["query"] == target
        calls = len(c.model_inputs)
        result = await c.send(answer)
        assert result.candidates and result.context.region == "성수동"
        assert c.reads == [("places", f"성수동 {target}")]
        assert len(c.model_inputs) == calls and not result.context.location_request
        assert c.place_id not in json.dumps(c.store.context)

    asyncio.run(run())


def test_location_selection_only_reads_the_explicit_id_and_retains_target(monkeypatch):
    async def run():
        c = LocationFlow(monkeypatch)
        await c.send("괜찮은 고깃집 있나?")
        result = await c.send("선택한 장소 주변에서 찾아줘.", selected=True)
        assert result.candidates and result.context.region == "중랑구 신내동"
        assert all(p.source == "naver" for p in result.candidates)
        assert [r for r in c.reads if r[0] == "places"] == [("places", "중랑구 신내동 고깃집")]
        assert c.place_id not in json.dumps(c.store.context)
        assert all("신내동 1" not in json.dumps(m) for m in c.model_inputs)
        assert result.context.location_request is None

    asyncio.run(run())


@pytest.mark.parametrize("destination", ["https://naver.me/synthetic", "경기도 양주시"])
def test_selected_place_without_a_neighborhood_keeps_question_open(monkeypatch, destination):
    async def run():
        c = LocationFlow(monkeypatch, destination=destination)
        await c.send("괜찮은 고깃집 있나?")
        result = await c.send("선택한 장소 주변에서 찾아줘.", selected=True)
        assert result.context.location_request and not [r for r in c.reads if r[0] == "places"]
        assert not any(p.source == "naver" for p in result.candidates)

    asyncio.run(run())


def test_social_cancel_and_new_request_do_not_resurrect_old_location_search(monkeypatch):
    async def run():
        c = LocationFlow(monkeypatch)
        await c.send("괜찮은 고깃집 있나?")
        result = await c.send("고마워")
        assert result.context.location_request["basis"] == c.store.version and not c.reads
        await c.send("검색은 그만해줘")
        assert c.store.context.get("location_request") is None
        await c.send("다시")
        assert not c.reads
        c.target = "카페"
        result = await c.send("성수동 카페 찾아줘")
        assert result.candidates and all("고깃집" not in r[1] for r in c.reads)

    asyncio.run(run())


def test_new_target_supersedes_location_question(monkeypatch):
    async def run():
        c = LocationFlow(monkeypatch)
        await c.send("괜찮은 고깃집 있나?")
        c.target = "카페"
        result = await c.send("성수동 카페 찾아줘")
        assert result.candidates and not result.context.location_request
        assert all("고깃집" not in r[1] for r in c.reads)

    asyncio.run(run())


@pytest.mark.parametrize("answer", ["모르겠어", "지역: https://example.test", "지역: 샘플 집"])
def test_unresolved_or_non_area_answer_keeps_location_question_and_target(monkeypatch, answer):
    async def run():
        c = LocationFlow(monkeypatch)
        await c.send("괜찮은 고깃집 있나?")
        result = await c.send(answer)
        assert result.context.location_request and not c.reads
        result = await c.send("지역: 성수동")
        assert result.candidates and c.reads == [("places", "성수동 고깃집")]

    asyncio.run(run())


@pytest.mark.parametrize("area", ["여기", "거기", "근처", "내 주변", "그 근처", "현재 위치"])
def test_deictic_locations_are_not_searchable_neighborhoods(area):
    from we2day_api.ai_place_policy import relational_area

    assert relational_area(area)
    assert not relational_area("중랑구 신내동")


def test_compound_spelling_matches_provider_category_without_adding_a_venue_dictionary():
    from we2day_api.ai_place_policy import PlacePolicy, SearchArguments, SearchScope, query_forms

    assert "고기" in query_forms("고깃집")
    assert "차" in query_forms("찻집")
    policy = PlacePolicy(
        SearchScope(area="성수동", kinds=["any"]), queries=[("any", "고깃집", "고깃집")]
    )
    args = SearchArguments(query="성수동 고깃집", kind="any", area="성수동")
    for category, expected in [("음식점>한식>육류,고기요리", True), ("음식점>카페", False)]:
        item = SearchResults.model_validate(
            {
                "items": [
                    {
                        "title": "합성 상호",
                        "category": category,
                        "roadAddress": "서울특별시 성동구 성수동 1",
                    }
                ]
            }
        ).items[0]
        assert policy.relevant(item, args) is expected


def test_new_private_reference_cannot_reuse_an_older_public_area_when_interpretation_omits_it(
    monkeypatch,
):
    async def run():
        c = LocationFlow(monkeypatch)
        await c.send("성수동 고깃집 찾아줘")
        before = len(c.reads)
        c.omit_area = True
        result = await c.send("다른 집 근처에서 보려고 하는데 괜찮은 고깃집 있어?")
        assert result.context.location_request and len(c.reads) == before
        assert result.context.location_request["scope"]["area"] == "다른 집"

    asyncio.run(run())


def test_a_selected_anchor_is_not_a_result_when_search_has_no_verified_candidates():
    from we2day_api.ai_place_policy import PlacePolicy, SearchScope
    from we2day_api.ai_tools import ToolSession

    session = ToolSession(
        SimpleNamespace(), None, [], [], PlacePolicy(SearchScope(kinds=["any"], search_only=True))
    )
    session.operation = "search"
    anchor = session.add("합성 기준점", "서울 성동구 성수동", "selected")
    session.fresh_refs.add(anchor.ref)
    session.selected_usage[anchor.ref] = "anchor"
    assert session.visible_candidates() == []
    assert session.candidates[anchor.ref] == anchor
