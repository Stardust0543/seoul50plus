import pandas as pd
import requests
import streamlit as st
import urllib.parse
import io
import datetime

st.set_page_config(
    page_title="서울시 50플러스 종합 정보 조회 서비스",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 퍼블리싱 스타일의 CSS 브랜딩 추가
st.markdown("""
    <style>
    .main-title {
        font-size: 38px;
        font-weight: 800;
        color: #1E3A8A;
        margin-bottom: 5px;
    }
    .sub-title {
        font-size: 16px;
        color: #4B5563;
        margin-bottom: 25px;
    }
    .stButton>button {
        background-color: #2563EB;
        color: white;
        border-radius: 6px;
        font-weight: bold;
    }
    .stDownloadButton>button {
        background-color: #10B981;
        color: white;
        border-radius: 6px;
    }
    </style>
    """, unsafe_allow_html=True)

st.markdown('<div class="main-title">📚 서울시 50플러스 통합 정보 조회 서비스</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">서울시 50플러스재단에서 제공하는 4대 OPEN API 정보를 조건별로 손쉽게 검색하고 다운로드 할 수 있는 웹앱입니다.</div>', unsafe_allow_html=True)

# 사이드바 설정
st.sidebar.header("⚙️ 서비스 설정")

# 기존 코드에 존재하던 디폴트 API 키 (사용자 화면에서 입력창 제거하여 비노출 처리)
default_key_encoded = "AAABoDKdAb60B414pbrYMXioj3hUsrvmSsaNoQ%3D%3D"
try:
    api_key = urllib.parse.unquote(default_key_encoded)
except Exception:
    api_key = default_key_encoded

# 조회연도 설정 (현재 날짜 연도 기본값, 풀다운 방식)
current_year = datetime.datetime.now().year
year_options = list(range(2020, current_year + 3))
default_year_index = year_options.index(current_year) if current_year in year_options else len(year_options) - 1

year = st.sidebar.selectbox(
    "조회 연도 선택",
    options=year_options,
    index=default_year_index
)

# 사이드바 메뉴 배치
menu_options = ["🎓 교육 과정", "🏢 시설 대관", "💼 일반 일자리", "🤝 가치동행 일자리"]
selected_menu = st.sidebar.radio(
    "📖 메뉴 선택",
    options=menu_options
)

# API 호출 캐싱 처리 (10분 유효)
@st.cache_data(ttl=600, show_spinner=False)
def fetch_api_data_cached(url, params_tuple):
    params = dict(params_tuple)
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(url, params=params, verify=False, timeout=15)
        if response.status_code == 200:
            data = response.json()
            header = data.get("response", {}).get("header", {})
            result_code = header.get("resultCode")
            result_msg = header.get("resultMsg", "알 수 없는 메시지")
            
            if result_code == "0000":
                body = data.get("response", {}).get("body", {})
                items = body.get("items", {})
                
                if items is None:
                    return [], 0
                
                item_data = items.get("item", [])
                if isinstance(item_data, dict):
                    item_data = [item_data]
                    
                total_count = body.get("totalCount", len(item_data))
                return item_data, total_count
            else:
                return {"error": f"API 에러 ({result_code}): {result_msg}"}, 0
        else:
            return {"error": f"HTTP 통신 실패 (상태 코드: {response.status_code})"}, 0
    except requests.exceptions.RequestException as e:
        return {"error": f"네트워크 오류: {e}"}, 0

def get_api_data(url, params):
    params_tuple = tuple(sorted(params.items()))
    res, total = fetch_api_data_cached(url, params_tuple)
    
    if isinstance(res, dict) and "error" in res:
        st.error(res["error"])
        return None, 0
    return res, total

def fetch_all_pages_with_error(url, params, load_limit=1000):
    with st.spinner("실시간 데이터를 수집하는 중..."):
        params = dict(params)
        params["pageNo"] = 1
        params["numOfRows"] = load_limit

        params_tuple = tuple(sorted(params.items()))
        items, total = fetch_api_data_cached(url, params_tuple)
        if isinstance(items, dict) and "error" in items:
            return None, 0, items["error"]

        all_items = list(items)
        if total > len(items):
            import math
            total_pages = math.ceil(total / load_limit)
            progress_bar = st.progress(0.1, text=f"전체 데이터를 수집 중... (1/{total_pages} 페이지)")

            for page in range(2, total_pages + 1):
                params["pageNo"] = page
                params_tuple = tuple(sorted(params.items()))
                page_items, _ = fetch_api_data_cached(url, params_tuple)
                if isinstance(page_items, dict) and "error" in page_items:
                    progress_bar.empty()
                    return None, 0, page_items["error"]
                if page_items:
                    all_items.extend(page_items)
                progress_bar.progress(page / total_pages, text=f"전체 데이터를 수집 중... ({page}/{total_pages} 페이지)")
            progress_bar.empty()

        return all_items, total, None

def fetch_all_pages_with_fallback(url, params_candidates, load_limit=1000):
    last_error = None
    for params in params_candidates:
        items, total, error = fetch_all_pages_with_error(url, params, load_limit=load_limit)
        if items is not None:
            return items, total, None
        last_error = error
    return None, 0, last_error

def build_multi_options(df, column):
    if column in df.columns:
        return sorted([v for v in df[column].dropna().astype(str).unique() if v != ""])
    return []

def apply_multi_select_filter(df, column, selected_values):
    if column in df.columns and selected_values:
        return df[df[column].astype(str).isin(selected_values)]
    return df

def ensure_data_loaded(session_key, url, params_candidates):
    if st.session_state.get(session_key):
        return

    items, total, error = fetch_all_pages_with_fallback(url, params_candidates)
    if items is not None:
        st.session_state[session_key] = items
        st.session_state[f"{session_key}_total"] = total
    elif error:
        st.error(error)

def to_excel_friendly_csv(df):
    return df.to_csv(index=False).encode("cp949", errors="replace")

# 데이터 전체 호출 헬퍼 함수
def fetch_all_pages(url, params, load_limit=1000):
    with st.spinner("실시간 데이터를 수집하는 중..."):
        params["pageNo"] = 1
        params["numOfRows"] = load_limit
        
        items, total = get_api_data(url, params)
        if items is None:
            return None, 0
            
        all_items = list(items)
        if total > len(items):
            import math
            total_pages = math.ceil(total / load_limit)
            progress_bar = st.progress(0.1, text=f"전체 데이터를 수집 중... (1/{total_pages} 페이지)")
            
            for page in range(2, total_pages + 1):
                params["pageNo"] = page
                page_items, _ = get_api_data(url, params)
                if page_items:
                    all_items.extend(page_items)
                progress_bar.progress(page / total_pages, text=f"전체 데이터를 수집 중... ({page}/{total_pages} 페이지)")
            progress_bar.empty()
            
        return all_items, total

# 캐시 초기화 버튼
if st.sidebar.button("🔄 캐시 데이터 강제 갱신"):
    st.cache_data.clear()
    st.sidebar.success("캐시가 초기화되었습니다! 새로 데이터를 조회합니다.")

st.sidebar.markdown("---")
st.sidebar.markdown("""
**💡 퍼블리싱 안내**
* 본 앱은 공공 데이터 API를 다룹니다.
* 데이터 조회가 지연될 경우 **캐시 데이터 강제 갱신**을 눌러주세요.
""")

# --- 1. 교육 과정 메뉴 ---
if selected_menu == "🎓 교육 과정":
    st.markdown("## 🎓 교육 과정 조회")
    st.caption("50플러스 교육 과정의 상세 조건 필터링 및 다운로드 기능을 제공합니다.")
    
    # 세션 상태 초기화 및 기본값 세팅
    if "edu_data" not in st.session_state:
        st.session_state["edu_data"] = []
        st.session_state["edu_total"] = 0

    ensure_data_loaded(
        "edu_data",
        "https://openapi.50plus.or.kr/openapi/service/education/list",
        [{"_type": "json", "accessKey": api_key, "year": year}]
    )

    st.markdown("### 🔍 조건 필터 및 상세 검색")
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        search_word = st.text_input("강좌명 / 강사명 검색", "", key="edu_f_word")
    with c2:
        temp_df = pd.DataFrame(st.session_state["edu_data"]) if st.session_state["edu_data"] else pd.DataFrame()
        org_options = build_multi_options(temp_df, "orgNm")
        sel_org = st.multiselect("개설 기관 선택", org_options, placeholder="선택하지 않으면 전체", key="edu_f_org")
    with c3:
        temp_df = pd.DataFrame(st.session_state["edu_data"]) if st.session_state["edu_data"] else pd.DataFrame()
        stat_options = build_multi_options(temp_df, "lctStatView")
        sel_stat = st.multiselect("모집 상태 선택", stat_options, placeholder="선택하지 않으면 전체", key="edu_f_stat")
    with c4:
        cost_option = st.selectbox("수강료 구분", ["전체", "무료", "유료"], key="edu_f_cost")
        
    c5, c6 = st.columns(2)
    with c5:
        start_date = st.date_input("검색 시작일", value=datetime.date.today(), key="edu_s_date")
    with c6:
        max_cost_limit = 500000
        if st.session_state["edu_data"]:
            temp_df = pd.DataFrame(st.session_state["edu_data"])
            if "lctCost" in temp_df.columns:
                try:
                    temp_df["lctCost"] = pd.to_numeric(temp_df["lctCost"], errors='coerce').fillna(0).astype(int)
                    max_val = int(temp_df["lctCost"].max())
                    if max_val > 0:
                        max_cost_limit = max_val
                except Exception:
                    pass
        selected_max_cost = st.slider("최대 수강료 범위(원)", 0, max_cost_limit, max_cost_limit, step=5000, key="edu_cost_slider")

    if st.session_state["edu_data"]:
        df = pd.DataFrame(st.session_state["edu_data"])
        
        edu_col_mapping = {
            "lctNm": "강좌명",
            "orgNm": "개설기관",
            "rpstLctr": "대표강사",
            "crPpl": "모집인원",
            "lctCost": "수강료(원)",
            "lctStatView": "모집상태",
            "lctTypeView": "강좌유형",
            "crStartDe": "강좌시작일",
            "crEndDe": "강좌종료일",
            "regStartDe": "접수시작일",
            "regEndDe": "접수종료일",
            "lctCtt": "강좌내용",
            "crYear": "개설연도"
        }
        df_rename = df.rename(columns=edu_col_mapping)
        
        filtered_df = df_rename.copy()
        
        if search_word:
            name_mask = filtered_df["강좌명"].astype(str).str.contains(search_word, case=False, na=False) if "강좌명" in filtered_df.columns else False
            lctr_mask = filtered_df["대표강사"].astype(str).str.contains(search_word, case=False, na=False) if "대표강사" in filtered_df.columns else False
            filtered_df = filtered_df[name_mask | lctr_mask]
            
        filtered_df = apply_multi_select_filter(filtered_df, "개설기관", sel_org)
        filtered_df = apply_multi_select_filter(filtered_df, "모집상태", sel_stat)
            
        if "수강료(원)" in filtered_df.columns:
            try:
                filtered_df["수강료(원)"] = pd.to_numeric(filtered_df["수강료(원)"], errors='coerce').fillna(0).astype(int)
            except Exception:
                pass
            if cost_option == "무료":
                filtered_df = filtered_df[filtered_df["수강료(원)"] == 0]
            elif cost_option == "유료":
                filtered_df = filtered_df[filtered_df["수강료(원)"] > 0]
            filtered_df = filtered_df[filtered_df["수강료(원)"] <= selected_max_cost]
            
        if "강좌시작일" in filtered_df.columns:
            try:
                filtered_df["temp_date"] = pd.to_datetime(filtered_df["강좌시작일"], errors='coerce').dt.date
                filtered_df = filtered_df[filtered_df["temp_date"] >= start_date]
                filtered_df = filtered_df.drop(columns=["temp_date"])
            except Exception:
                pass
            
        st.success(f"🎉 필터링 결과: 총 {len(filtered_df)}건 검색됨 (전체 로드 건수: {len(df_rename)})")
        
        display_cols = ["강좌명", "개설기관", "모집상태", "수강료(원)", "모집인원", "대표강사", "강좌시작일", "강좌종료일", "접수시작일", "접수종료일"]
        existing_display_cols = [c for c in display_cols if c in filtered_df.columns]
        other_cols = [c for c in filtered_df.columns if c not in existing_display_cols]
        filtered_df = filtered_df[existing_display_cols + other_cols]

        st.dataframe(filtered_df, use_container_width=True)
        
        csv_data = to_excel_friendly_csv(filtered_df)
        st.download_button(
            label="📥 필터링된 교육 리스트 CSV 다운로드",
            data=csv_data,
            file_name=f"seoul50plus_edu_{year}.csv",
            mime="text/csv",
            use_container_width=True
        )

# --- 2. 시설 대관 메뉴 ---
elif selected_menu == "🏢 시설 대관":
    st.markdown("## 🏢 시설 대관 정보 조회")
    st.caption("50플러스 대관 현황을 날짜, 기관, 대관유형으로 통합 필터링 및 다운로드합니다.")
    
    if "rent_data" not in st.session_state:
        st.session_state["rent_data"] = []
        st.session_state["rent_total"] = 0

    ensure_data_loaded(
        "rent_data",
        "https://openapi.50plus.or.kr/openapi/service/rental/list",
        [{"_type": "json", "accessKey": api_key, "year": year}]
    )
        
    st.markdown("### 🔍 조건 필터 및 상세 검색")
    c1, c2, c3 = st.columns(3)
    with c1:
        temp_df = pd.DataFrame(st.session_state["rent_data"]) if st.session_state["rent_data"] else pd.DataFrame()
        org_options = build_multi_options(temp_df, "orgNm")
        sel_org = st.multiselect("기관 선택", org_options, placeholder="선택하지 않으면 전체", key="rent_f_org")
    with c2:
        temp_df = pd.DataFrame(st.session_state["rent_data"]) if st.session_state["rent_data"] else pd.DataFrame()
        stat_options = build_multi_options(temp_df, "bookingStatNm")
        sel_stat = st.multiselect("예약 유형 선택", stat_options, placeholder="선택하지 않으면 전체", key="rent_f_stat")
    with c3:
        room_word = st.text_input("강의실명 검색", "", key="rent_f_room")
        
    c4, c5 = st.columns(2)
    with c4:
        start_date = st.date_input("검색 시작일", value=datetime.date.today(), key="rent_s_date")
        
    if st.session_state["rent_data"]:
        df = pd.DataFrame(st.session_state["rent_data"])
        
        rent_col_mapping = {
            "bookingStatNm": "예약상태명",
            "orgNm": "기관명",
            "roomNm": "강의실명",
            "cfmDeView": "확정일",
            "cfmSttmView": "시작시간",
            "cfmEdtmView": "종료시간"
        }
        df_rename = df.rename(columns=rent_col_mapping)
        
        filtered_df = df_rename.copy()
        filtered_df = apply_multi_select_filter(filtered_df, "기관명", sel_org)
        filtered_df = apply_multi_select_filter(filtered_df, "예약상태명", sel_stat)
        if "강의실명" in filtered_df.columns and room_word:
            filtered_df = filtered_df[filtered_df["강의실명"].astype(str).str.contains(room_word, case=False, na=False)]
        if "확정일" in filtered_df.columns:
            try:
                filtered_df["temp_date"] = pd.to_datetime(filtered_df["확정일"], errors='coerce').dt.date
                filtered_df = filtered_df[filtered_df["temp_date"] >= start_date]
                filtered_df = filtered_df.drop(columns=["temp_date"])
            except Exception:
                pass
            
        st.success(f"🎉 필터링 결과: 총 {len(filtered_df)}건 검색됨 (전체 로드 건수: {len(df_rename)})")
        
        display_cols = ["기관명", "강의실명", "예약상태명", "확정일", "시작시간", "종료시간"]
        existing_display_cols = [c for c in display_cols if c in filtered_df.columns]
        other_cols = [c for c in filtered_df.columns if c not in existing_display_cols]
        filtered_df = filtered_df[existing_display_cols + other_cols]
        
        st.dataframe(filtered_df, use_container_width=True)
        
        csv_data = to_excel_friendly_csv(filtered_df)
        st.download_button(
            label="📥 필터링된 대관 리스트 CSV 다운로드",
            data=csv_data,
            file_name=f"seoul50plus_rental_{year}.csv",
            mime="text/csv",
            use_container_width=True
        )

# --- 3. 일반 일자리 메뉴 ---
elif selected_menu == "💼 일반 일자리":
    st.markdown("## 💼 일반 일자리 조회")
    st.caption("50플러스 일자리를 사업명, 기관, 활동비, 상태 등으로 통합 필터링 및 다운로드합니다.")
    
    if "job_data" not in st.session_state:
        st.session_state["job_data"] = []
        st.session_state["job_total"] = 0

    ensure_data_loaded(
        "job_data",
        "https://openapi.50plus.or.kr/openapi/service/job2/list",
        [
            {"_type": "json", "accessKey": api_key, "year": year},
            {"_type": "json", "accessKey": api_key},
        ]
    )
        
    st.markdown("### 🔍 조건 필터 및 상세 검색")
    c1, c2, c3 = st.columns(3)
    with c1:
        search_word = st.text_input("사업명 / 사업구분 검색", "", key="job_f_word")
    with c2:
        temp_df = pd.DataFrame(st.session_state["job_data"]) if st.session_state["job_data"] else pd.DataFrame()
        org_options = build_multi_options(temp_df, "orgNm")
        sel_org = st.multiselect("운영 기관 선택", org_options, placeholder="선택하지 않으면 전체", key="job_f_org")
    with c3:
        temp_df = pd.DataFrame(st.session_state["job_data"]) if st.session_state["job_data"] else pd.DataFrame()
        stat_options = build_multi_options(temp_df, "annRcrtStatNm")
        sel_stat = st.multiselect("모집 상태 선택", stat_options, placeholder="선택하지 않으면 전체", key="job_f_stat")
        
    c4, c5 = st.columns(2)
    with c4:
        start_date = st.date_input("검색 시작일", value=datetime.date.today(), key="job_ref_date")
    with c5:
        max_pay = 1000000
        if st.session_state["job_data"]:
            temp_df = pd.DataFrame(st.session_state["job_data"])
            if "actamtHamt" in temp_df.columns:
                try:
                    temp_df["actamtHamt"] = pd.to_numeric(temp_df["actamtHamt"], errors='coerce').fillna(0).astype(int)
                    max_val = int(temp_df["actamtHamt"].max())
                    if max_val > 0:
                        max_pay = max_val
                except Exception:
                    pass
        sel_pay = st.slider("최소 활동비 금액(원)", 0, max_pay, 0, step=10000, key="job_pay_slider")
        
    if st.session_state["job_data"]:
        df = pd.DataFrame(st.session_state["job_data"])
        
        job_col_mapping = {
            "bizNm": "사업명",
            "bizSeNm": "사업구분명",
            "orgNm": "운영기관명",
            "rcrtPpl": "모집인원",
            "actamtHamt": "활동비(원)",
            "annRcrtStatNm": "공고모집상태",
            "actperStartDe": "활동시작일",
            "actperEndDe": "활동종료일",
            "appdurngStartDe": "신청시작일",
            "appdurngEndDe": "신청종료일",
            "bizYear": "사업연도"
        }
        df_rename = df.rename(columns=job_col_mapping)
        
        if "활동비(원)" in df_rename.columns:
            df_rename["활동비(원)"] = pd.to_numeric(df_rename["활동비(원)"], errors='coerce').fillna(0).astype(int)
        
        filtered_df = df_rename.copy()
        if search_word:
            biz_mask = filtered_df["사업명"].astype(str).str.contains(search_word, case=False, na=False) if "사업명" in filtered_df.columns else False
            se_mask = filtered_df["사업구분명"].astype(str).str.contains(search_word, case=False, na=False) if "사업구분명" in filtered_df.columns else False
            filtered_df = filtered_df[biz_mask | se_mask]
        filtered_df = apply_multi_select_filter(filtered_df, "운영기관명", sel_org)
        filtered_df = apply_multi_select_filter(filtered_df, "공고모집상태", sel_stat)
        if "활동비(원)" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["활동비(원)"] >= sel_pay]
        if "신청종료일" in filtered_df.columns:
            try:
                filtered_df["end_dt"] = pd.to_datetime(filtered_df["신청종료일"], errors='coerce').dt.date
                filtered_df = filtered_df[filtered_df["end_dt"] >= start_date]
                filtered_df = filtered_df.drop(columns=["end_dt"])
            except Exception:
                pass
            
        st.success(f"🎉 필터링 결과: 총 {len(filtered_df)}건 검색됨 (전체 로드 건수: {len(df_rename)})")
        
        display_cols = ["사업명", "사업구분명", "운영기관명", "공고모집상태", "활동비(원)", "모집인원", "신청시작일", "신청종료일"]
        existing_display_cols = [c for c in display_cols if c in filtered_df.columns]
        other_cols = [c for c in filtered_df.columns if c not in existing_display_cols]
        filtered_df = filtered_df[existing_display_cols + other_cols]
        
        st.dataframe(filtered_df, use_container_width=True)
        
        csv_data = to_excel_friendly_csv(filtered_df)
        st.download_button(
            label="📥 필터링된 일자리 리스트 CSV 다운로드",
            data=csv_data,
            file_name=f"seoul50plus_job_{year}.csv",
            mime="text/csv",
            use_container_width=True
        )

# --- 4. 가치동행 일자리 메뉴 ---
elif selected_menu == "🤝 가치동행 일자리":
    st.markdown("## 🤝 가치동행 일자리 조회")
    st.caption("50플러스 가치동행일자리를 상세 조건에 따라 필터링 및 다운로드합니다.")
    
    if "vjob_data" not in st.session_state:
        st.session_state["vjob_data"] = []
        st.session_state["vjob_total"] = 0

    ensure_data_loaded(
        "vjob_data",
        "https://openapi.50plus.or.kr/openapi/service/job1/list",
        [{"_type": "json", "accessKey": api_key, "year": year}]
    )
        
    st.markdown("### 🔍 조건 필터 및 상세 검색")
    c1, c2, c3 = st.columns(3)
    with c1:
        search_word = st.text_input("가치동행 사업명 검색", "", key="vjob_f_word")
    with c2:
        temp_df = pd.DataFrame(st.session_state["vjob_data"]) if st.session_state["vjob_data"] else pd.DataFrame()
        org_options = build_multi_options(temp_df, "orgNm")
        sel_org = st.multiselect("운영 기관 선택", org_options, placeholder="선택하지 않으면 전체", key="vjob_f_org")
    with c3:
        temp_df = pd.DataFrame(st.session_state["vjob_data"]) if st.session_state["vjob_data"] else pd.DataFrame()
        stat_options = build_multi_options(temp_df, "annApprvStatView")
        sel_stat = st.multiselect("공고 승인 상태 선택", stat_options, placeholder="선택하지 않으면 전체", key="vjob_f_stat")
        
    c4, c5 = st.columns(2)
    with c4:
        start_date = st.date_input("검색 시작일", value=datetime.date.today(), key="vjob_ref_date")
    with c5:
        max_pay = 1000000
        if st.session_state["vjob_data"]:
            temp_df = pd.DataFrame(st.session_state["vjob_data"])
            if "actamtHamt" in temp_df.columns:
                try:
                    temp_df["actamtHamt"] = pd.to_numeric(temp_df["actamtHamt"], errors='coerce').fillna(0).astype(int)
                    max_val = int(temp_df["actamtHamt"].max())
                    if max_val > 0:
                        max_pay = max_val
                except Exception:
                    pass
        sel_pay = st.slider("최소 활동비 금액(원)", 0, max_pay, 0, step=10000, key="vjob_pay_slider")
        
    if st.session_state["vjob_data"]:
        df = pd.DataFrame(st.session_state["vjob_data"])
        
        vjob_col_mapping = {
            "bizNm": "사업명",
            "orgNm": "운영기관명",
            "rcrtPpl": "모집인원",
            "actamtHamt": "활동비(원)",
            "annApprvStatView": "공고승인상태",
            "actperStartDe": "활동시작일",
            "actperEndDe": "활동종료일",
            "appdurngStartDe": "신청시작일",
            "appdurngEndDe": "신청종료일",
            "bizYear": "사업연도"
        }
        df_rename = df.rename(columns=vjob_col_mapping)
        
        if "활동비(원)" in df_rename.columns:
            df_rename["활동비(원)"] = pd.to_numeric(df_rename["활동비(원)"], errors='coerce').fillna(0).astype(int)
        
        filtered_df = df_rename.copy()
        if search_word:
            filtered_df = filtered_df[filtered_df["사업명"].astype(str).str.contains(search_word, case=False, na=False)]
        filtered_df = apply_multi_select_filter(filtered_df, "운영기관명", sel_org)
        filtered_df = apply_multi_select_filter(filtered_df, "공고승인상태", sel_stat)
        if "활동비(원)" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["활동비(원)"] >= sel_pay]
        if "신청종료일" in filtered_df.columns:
            try:
                filtered_df["end_dt"] = pd.to_datetime(filtered_df["신청종료일"], errors='coerce').dt.date
                filtered_df = filtered_df[filtered_df["end_dt"] >= start_date]
                filtered_df = filtered_df.drop(columns=["end_dt"])
            except Exception:
                pass
            
        st.success(f"🎉 필터링 결과: 총 {len(filtered_df)}건 검색됨 (전체 로드 건수: {len(df_rename)})")
        
        display_cols = ["사업명", "운영기관명", "공고승인상태", "활동비(원)", "모집인원", "신청시작일", "신청종료일"]
        existing_display_cols = [c for c in display_cols if c in filtered_df.columns]
        other_cols = [c for c in filtered_df.columns if c not in existing_display_cols]
        filtered_df = filtered_df[existing_display_cols + other_cols]
        
        st.dataframe(filtered_df, use_container_width=True)
        
        csv_data = to_excel_friendly_csv(filtered_df)
        st.download_button(
            label="📥 필터링된 가치동행 리스트 CSV 다운로드",
            data=csv_data,
            file_name=f"seoul50plus_vjob_{year}.csv",
            mime="text/csv",
            use_container_width=True
        )

