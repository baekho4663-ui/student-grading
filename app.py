import copy
import hashlib
import io
import json
import os

import streamlit as st
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
from grading import STATUSES, ai_grade, demo_grade, draft_record, export_excel

load_dotenv()
st.set_page_config(page_title="수행평가 채점 도우미", page_icon="📝", layout="wide")
st.title("📝 수행평가 채점 도우미")
st.caption("학생 1명 시험용 · AI 제안은 교사가 확인하고 최종 확정합니다.")

with st.sidebar:
    st.header("실행 설정")
    mode = st.radio("채점 방식", ["체험 모드 (API 키 불필요)", "실제 AI 채점"])
    is_demo = mode.startswith("체험")
    key_input = st.text_input("OpenAI API 키 (이번 실행에서만 사용)", type="password")
    key = key_input.strip() or os.getenv("OPENAI_API_KEY", "")
    model = st.text_input("이미지 입력 지원 모델", value=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    st.caption("키는 저장소에 저장하지 않습니다. 실제 AI 요청에는 API 요금이 발생할 수 있습니다.")
    consent = st.checkbox("실제 AI 사용 시 답안 사진·문제·기준 및 세특 생성용 평가·관찰 기록이 OpenAI로 전송됨을 확인했습니다.")
    st.info("사진에서 이름·학번 등 개인정보를 가리고, 학교의 외부 AI 이용 지침을 확인하세요.")

st.header("1. 문제와 답안 입력")
student = st.text_input("학생 표시명 (가명 권장)", "학생 A")
count = st.number_input("문항 수", min_value=1, max_value=10, value=1)
questions = []
for i in range(count):
    with st.expander(f"{i + 1}번 문제 / 채점기준", expanded=True):
        prompt = st.text_area("문제", value="식물의 광합성에 필요한 조건과 그 결과를 설명하세요." if i == 0 else "", key=f"prompt_{i}")
        maximum = st.number_input("배점", min_value=1, max_value=100, value=10, key=f"maximum_{i}")
        rubric = st.text_area("채점기준 (요소별 점수와 부분점수 규칙을 구체적으로 작성)",
            value="빛 2점, 물 2점, 이산화탄소 2점, 포도당 생성 2점, 산소 방출 2점. 언급한 요소별로 점수를 합산한다." if i == 0 else "", key=f"rubric_{i}")
        elements = st.text_area("반드시 요구한 요소 (한 줄에 하나)", value="빛\n물\n이산화탄소\n포도당 생성\n산소 방출" if i == 0 else "", key=f"required_{i}")
        questions.append({"prompt": prompt.strip(), "max_score": maximum, "rubric": rubric.strip(), "required": list(dict.fromkeys(e.strip() for e in elements.splitlines() if e.strip()))})

uploads = st.file_uploader("학생 1명의 답안 사진 (PNG/JPG, 여러 장 가능 / 합계 20MB 이하)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
photos = [{"bytes": p.getvalue(), "mime": "image/png" if p.name.lower().endswith(".png") else "image/jpeg"} for p in uploads]
oversize = sum(len(p["bytes"]) for p in photos) > 20 * 1024 * 1024
invalid_image = False
if not oversize:
    for photo in photos:
        try:
            with Image.open(io.BytesIO(photo["bytes"])) as image:
                if image.format not in ("JPEG", "PNG") or image.width * image.height > 25_000_000:
                    raise ValueError("지원하지 않는 이미지")
                photo["mime"] = "image/png" if image.format == "PNG" else "image/jpeg"
                image.verify()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            invalid_image = True
if oversize:
    st.error("사진 합계를 20MB 이하로 줄여 주세요.")
elif invalid_image:
    st.error("사진을 열 수 없습니다. 정상적인 JPG/PNG 파일인지 확인하고, 사진 한 장을 2,500만 화소 이하로 줄여 주세요.")
elif photos:
    for p in photos:
        st.image(p["bytes"], width=350)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

source = fingerprint({"questions": questions, "photos": [hashlib.sha256(p["bytes"]).hexdigest() for p in photos], "mode": mode, "model": model, "student": student})
if st.session_state.get("source") != source:
    for name in ["initial", "confirmed", "record", "record_source"]:
        st.session_state.pop(name, None)
    st.session_state.source = source

if is_demo:
    st.warning("체험 모드는 사진을 읽거나 실제 채점하지 않습니다. 예시 0점과 ‘확인 불가’를 생성하여 수정·확정·다운로드 흐름을 시험합니다. 사진 없이도 진행할 수 있습니다.")
if st.button("체험 결과 만들기" if is_demo else "AI 채점 제안 받기", type="primary"):
    if any(not q["prompt"] or not q["rubric"] or not q["required"] for q in questions):
        st.error("모든 문항의 문제, 채점기준, 필수 요소를 입력하세요.")
    elif oversize or invalid_image:
        st.error("사진 형식과 크기를 확인해 주세요.")
    elif not is_demo and (not key or not consent or not photos):
        st.error("API 키, 전송 확인, 답안 사진이 모두 필요합니다.")
    else:
        try:
            with st.spinner("채점 결과를 준비하고 있습니다…"):
                result = demo_grade(questions) if is_demo else ai_grade(key, model, questions, photos)
            st.session_state.initial = result
            st.session_state.generation = st.session_state.get("generation", 0) + 1
            for name in ["confirmed", "record", "record_source"]:
                st.session_state.pop(name, None)
        except Exception:
            st.error("채점 요청에 실패했습니다. 키·잔액·모델의 이미지/구조화 출력 지원·네트워크를 확인하세요. 입력은 유지됩니다. 다시 시도할 수 있습니다.")

if "initial" in st.session_state:
    st.header("2. 교사 검토 및 최종 확정")
    st.caption("사진과 필수 요소별 증거를 확인하고 점수·판단·근거를 수정하세요. 입력을 변경하면 확정을 다시 해야 합니다.")
    edited = copy.deepcopy(st.session_state.initial)
    generation = st.session_state.generation
    for i, row in enumerate(edited):
        with st.expander(f"{i + 1}번 검토", expanded=True):
            st.write("최초 제안:", st.session_state.initial[i]["reason"])
            row["score"] = st.number_input("교사 점수", min_value=0.0, max_value=float(questions[i]["max_score"]), value=float(row["score"]), step=0.5, key=f"score_{generation}_{i}")
            row["reason"] = st.text_area("교사 채점 근거", value=row["reason"], key=f"reason_{generation}_{i}")
            for j, check in enumerate(row["checks"]):
                st.markdown(f"**필수 요소 {j + 1}:** {check['element']}")
                check["status"] = st.selectbox("요소 충족 여부", STATUSES, index=STATUSES.index(check["status"]), key=f"status_{generation}_{i}_{j}")
                check["evidence"] = st.text_area("답안 증거 / 교사 확인 내용", value=check["evidence"], key=f"evidence_{generation}_{i}_{j}")
    review_hash = fingerprint(edited)
    if st.session_state.get("confirmed") and st.session_state.confirmed["hash"] != review_hash:
        for name in ["confirmed", "record", "record_source"]:
            st.session_state.pop(name, None)
    st.metric("현재 총점", f"{sum(r['score'] for r in edited):g} / {sum(q['max_score'] for q in questions)}")
    reviewed = st.checkbox("모든 문항의 점수·근거와 ‘확인 불가’ 항목을 직접 검토했습니다.", key=f"reviewed_{generation}_{review_hash}")
    if st.button("교사 최종 확정", disabled=not reviewed):
        if any(not r["reason"].strip() or any(not c["evidence"].strip() for c in r["checks"]) for r in edited):
            st.error("각 문항의 근거와 필수 요소별 확인 내용을 입력하세요.")
        else:
            st.session_state.confirmed = {"hash": review_hash, "rows": copy.deepcopy(edited)}

    if "confirmed" in st.session_state:
        st.success("교사 최종 확정 완료" + (" (체험 데이터)" if is_demo else ""))
        st.header("3. 세특 초안과 엑셀 다운로드")
        observation = st.text_area("교사 관찰 기록 (실제로 관찰한 활동·발언·과정만 입력)", placeholder="예: 실험 결과를 표로 정리하고, 모둠 발표에서 관찰 결과를 설명함.")
        record_source = fingerprint({"review": review_hash, "observation": observation})
        if st.session_state.get("record_source") != record_source:
            st.session_state.pop("record", None)
        if st.button("세특 초안 만들기"):
            if not observation.strip():
                st.error("실제로 관찰한 내용을 먼저 입력하세요.")
            elif not is_demo and (not key or not consent):
                st.error("API 키와 외부 전송 확인이 필요합니다.")
            else:
                try:
                    with st.spinner("초안을 작성하고 있습니다…"):
                        record = ("[체험용 템플릿 — 실제 AI 작성 아님]\n교사 관찰 기록: " + observation + "\n답안에서 확인한 학습 내용과 수행 과정을 교사가 덧붙여 완성하세요.") if is_demo else draft_record(key, model, questions, edited, observation)
                    st.session_state.record = record
                    st.session_state.record_source = record_source
                except Exception:
                    st.error("세특 생성에 실패했습니다. API 설정과 잔액을 확인하고 다시 시도하세요.")
        record = ""
        if "record" in st.session_state:
            record = st.text_area("세특 초안 (교사가 수정 가능)", value=st.session_state.record, height=180, key=f"record_editor_{fingerprint(st.session_state.record)}_{record_source}")
        st.caption("엑셀에는 확정 점수·필수 요소 확인·최초 제안·관찰 기록·현재 세특 초안이 포함됩니다. 세특을 생성하지 않아도 채점 결과를 내려받을 수 있습니다.")
        st.download_button("확정 결과 엑셀 다운로드", export_excel(student, questions, st.session_state.initial, edited, observation, record, mode), file_name="grading_result.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.divider()
st.caption("입력 자료는 앱이 파일로 저장하지 않습니다. 브라우저 새로고침·연결 종료·서버 재시작 시 사라질 수 있으니 엑셀로 보관하세요. 실제 AI 전송 자료의 처리는 제공업체 정책을 따릅니다.")
