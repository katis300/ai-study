# d:\gemma-wms\chart_utils.py
import datetime
from flask import current_app # 로거 사용을 위해 추가
import decimal

# --- 공통 차트 색상 ---
CHART_BACKGROUND_COLORS = ['rgba(54, 162, 235, 0.5)', 'rgba(255, 99, 132, 0.5)', 'rgba(255, 206, 86, 0.5)', 'rgba(75, 192, 192, 0.5)', 'rgba(153, 102, 255, 0.5)', 'rgba(255, 159, 64, 0.5)', 'rgba(255, 159, 200, 0.5)', 'rgba(100, 159, 64, 0.5)']
CHART_BORDER_COLORS = ['rgba(54, 162, 235, 1)', 'rgba(255, 99, 132, 1)', 'rgba(255, 206, 86, 1)', 'rgba(75, 192, 192, 1)', 'rgba(153, 102, 255, 1)', 'rgba(255, 159, 64, 1)', 'rgba(255, 159, 200, 1)', 'rgba(100, 159, 64, 1)']

def _get_chart_colors(num_items, color_list):
    return color_list * ((num_items // len(color_list)) + 1)

# --- 차트 데이터 준비 함수 ---
def prepare_chart_data(original_question: str, rows: list, column_names: list, generated_sql: str, column_name_korean_map: dict):
    chart_config = None
    chart_notice = None
    chart_notice_prev_result = None
    num_rows = len(rows)
    num_cols = len(column_names)

    if not rows or num_rows == 0:
        current_app.logger.debug("CHART_UTILS: No rows, skipping chart generation.")
        return None, None

    question_lower = original_question.lower()

    # 사용자가 명시적으로 차트를 요청했는지 확인하는 키워드 목록
    general_chart_keywords = [
        # 한글
        "그래프", "차트", "도표", "도식", "그림", "그림으로", "시각화", "분포도", "비율", "비중", "비교", "비교표", "비교그래프", "비교 차트",
        "원그래프", "파이차트", "파이 차트", "원 차트", "원차트", "파이그래프", "파이 그래프", "원형그래프", "원형 그래프", "원형차트", "원형 차트",
        "막대그래프", "막대 그래프", "막대차트", "막대 차트", "바그래프", "바 그래프", "바차트", "바 차트", "막대도표", "막대 도표",
        "선그래프", "선 그래프", "선차트", "선 차트", "라인그래프", "라인 그래프", "라인차트", "라인 차트", "추이", "추이표", "추이 그래프",
        "꺾은선그래프", "꺾은선 그래프", "꺾은선차트", "꺾은선 차트", "꺾은선도표", "꺾은선 도표",
        "분포그래프", "분포 그래프", "분포차트", "분포 차트", "분포도표", "분포 도표",
        "히스토그램", "히스토그램 차트", "히스토그램 그래프",
        "스택그래프", "스택 그래프", "스택차트", "스택 차트", "누적그래프", "누적 그래프", "누적차트", "누적 차트",
        "비주얼", "비주얼라이즈", "비주얼라이제이션", "시각화해줘", "시각화해 주세요", "그림으로 보여줘", "그림으로 보여 주세요",
        # 영문
        "graph", "chart", "plot", "visual", "visualize", "visualization", "diagram", "pie", "bar", "line", "stack", "stacked", "histogram", "distribution",
        "pie chart", "bar chart", "line chart", "stacked chart", "stacked bar", "stacked line", "histogram chart", "distribution chart",
        # 자연어/복합
        "비율로", "비중으로", "비교해서", "비교로", "분포로", "추이로", "변화", "변화추이", "변화 그래프", "변화 차트",
        "원그래프 그려줘", "파이그래프 그려줘", "막대그래프 그려줘", "선그래프 그려줘", "라인그래프 그려줘", "히스토그램 그려줘",
        "그래프로", "차트로", "도표로", "그림으로", "시각화로", "분포로", "비율로", "비중으로", "비교로", "추이로", "변화로"
    ]
    requested_any_chart = any(keyword in question_lower for keyword in general_chart_keywords)

    if not requested_any_chart:
        current_app.logger.debug("CHART_UTILS: No explicit chart request keywords found in the question. Skipping chart generation.")
        return None, None

    requested_pie_chart = any(keyword in question_lower for keyword in [
        "원그래프", "원 그래프", "파이차트", "파이 차트", "원 차트", "원차트", "파이그래프", "파이 그래프"
    ])
    requested_bar_chart = any(keyword in question_lower for keyword in [
        "막대그래프", "바차트", "바 차트", "막대 차트", "막대차트", "막대 그래프", "바 그래프"
    ])

    # Helper to find the best data column for charts (e.g., qty, total_qty, count)
    def find_chart_data_column(cols, rows_data, label_col_name_to_exclude=None):
        numeric_cols = []
        if rows_data and len(rows_data) > 0:
            first_row = rows_data[0]
            for i, col_name_iter in enumerate(cols):
                if isinstance(first_row[i], (int, float, decimal.Decimal)):
                    if label_col_name_to_exclude and col_name_iter.lower() == label_col_name_to_exclude.lower():
                        continue # Skip if it's the label column
                    numeric_cols.append(col_name_iter)
        
        if not numeric_cols:
            return None

        # Priority 1 & 2: qty related columns
        qty_variants = ['qty', 'total_qty', 'sum_qty', 'jego_qty', 'ordqty', 'reqqty']
        for variant_lower in [v.lower() for v in qty_variants]: # Compare lowercase
            for nc in numeric_cols:
                if nc.lower() == variant_lower: return nc
        
        for nc in numeric_cols: # Check for columns ending with _qty
            if nc.lower().endswith('_qty'): return nc

        # Priority 3: count related columns
        count_variants = ['count', 'total_count', 'cnt']
        for variant_lower in [v.lower() for v in count_variants]: # Compare lowercase
            for nc in numeric_cols:
                if nc.lower() == variant_lower: return nc
        for nc in numeric_cols: # Check for columns ending with _cnt or _count
            if nc.lower().endswith('_cnt') or nc.lower().endswith('_count'): return nc
        
        return numeric_cols[0] if numeric_cols else None # Fallback to first numeric

    # Helper to get Korean display name for a column, considering common aliases
    def get_korean_col_name_for_chart(col_name_eng_original_case, cmap):
        col_name_eng_lower = col_name_eng_original_case.lower()
        # Try direct match first (e.g. if 'total_qty' itself is mapped)
        if col_name_eng_lower in cmap:
            return cmap[col_name_eng_lower]
        
        # Handle aliases by checking for base terms
        if 'qty' in col_name_eng_lower: # Covers 'qty', 'total_qty', 'sum_qty', 'item_qty'
            return cmap.get('qty', col_name_eng_original_case) # Fallback to original if 'qty' not in map
        elif 'count' in col_name_eng_lower or 'cnt' in col_name_eng_lower: # Covers 'count', 'total_count', 'item_cnt'
            return cmap.get('count', cmap.get('cnt', col_name_eng_original_case)) # Fallback for count/cnt
        
        return col_name_eng_original_case # Absolute fallback

    if requested_pie_chart:
        current_app.logger.debug(f"CHART_UTILS_PIE: 파이그래프 조건 진입, 컬럼: {column_names}")
        label_col_name = 'jpname'  # Typically product name for pie charts
        
        if label_col_name not in column_names:
            current_app.logger.debug(f"CHART_UTILS_PIE: 필수 레이블 컬럼 '{label_col_name}'이(가) 없습니다. 파이그래프 생성 불가.")
        else:
            data_col_name = find_chart_data_column(column_names, rows, label_col_name)

            if data_col_name:
                label_col_idx = column_names.index(label_col_name)
                data_col_idx = column_names.index(data_col_name)
                
                data_col_korean_name = get_korean_col_name_for_chart(data_col_name, column_name_korean_map)
                label_col_korean_name = column_name_korean_map.get(label_col_name.lower(), label_col_name)

                aggregated_data = {}
                for row in rows:
                    label_val = str(row[label_col_idx])
                    try:
                        data_val = float(row[data_col_idx])
                        aggregated_data[label_val] = aggregated_data.get(label_val, 0) + data_val
                    except (ValueError, TypeError):
                        continue
                current_app.logger.debug(f"CHART_UTILS_PIE: 파이그래프 집계 결과 ({label_col_name}, {data_col_name}): {aggregated_data}")
                if len(aggregated_data) > 1: # Need at least 2 segments for a meaningful pie chart
                    agg_labels = list(aggregated_data.keys())
                    agg_data_values = list(aggregated_data.values())
                    chart_title = f"{label_col_korean_name}별 {data_col_korean_name} 분포"
                    chart_config = {
                        "type": "pie",
                        "data": {
                            "labels": agg_labels,
                            "datasets": [{
                                "label": data_col_korean_name,
                                "data": agg_data_values,
                                "backgroundColor": _get_chart_colors(len(agg_labels), CHART_BACKGROUND_COLORS),
                                "borderColor": _get_chart_colors(len(agg_labels), CHART_BORDER_COLORS),
                                "borderWidth": 1
                            }]
                        },
                        "options": {
                            "responsive": True,
                            "maintainAspectRatio": False,
                            "plugins": {
                                "legend": {"display": True, "position": 'top'},
                                "title": {"display": True, "text": chart_title}
                            }
                        }
                    }
                    current_app.logger.debug(f"CHART_UTILS_PIE: Pie chart config generated with {len(agg_labels)} categories. Label: {label_col_name}, Data: {data_col_name}")
                    current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
                    return chart_config, None
                elif len(aggregated_data) == 1:
                    chart_notice = "요청하신 파이차트는 데이터 항목이 하나뿐이라 바차트로 대체되었습니다."
                    # Fall through to bar chart logic by not returning here
                else: # No data after aggregation
                    current_app.logger.debug(f"CHART_UTILS_PIE: 집계 후 데이터가 없어 파이차트를 생성할 수 없습니다.")
            else:
                current_app.logger.debug(f"CHART_UTILS_PIE: 적절한 데이터 컬럼을 찾지 못했습니다. 컬럼: {column_names}. 파이그래프 생성 불가.")

    if requested_bar_chart or (requested_pie_chart and chart_notice): # Also try bar if pie had only 1 item
        current_app.logger.debug(f"CHART_UTILS_BAR: 바차트 조건 진입 (또는 파이차트 대체), 컬럼: {column_names}")
        label_col_name = 'jpname' 
        if label_col_name not in column_names: # If 'jpname' not present, try a date column
            date_col_candidates_bar = [col for col in column_names if col.lower() in {"indat", "jego_ymd", "orddate", "reqdat", "otdat", "proddat"}]
            if date_col_candidates_bar:
                label_col_name = date_col_candidates_bar[0]

        if label_col_name not in column_names:
             current_app.logger.debug(f"CHART_UTILS_BAR: 적절한 레이블 컬럼을 찾지 못했습니다 (jpname 또는 날짜 컬럼). 바차트 생성 불가.")
        else:
            data_col_name = find_chart_data_column(column_names, rows, label_col_name)
            if data_col_name:
                label_col_idx = column_names.index(label_col_name)
                data_col_idx = column_names.index(data_col_name)

                data_col_korean_name = get_korean_col_name_for_chart(data_col_name, column_name_korean_map)
                label_col_korean_name = column_name_korean_map.get(label_col_name.lower(), label_col_name)
                
                aggregated_data = {}
                for row in rows:
                    label_val = str(row[label_col_idx])
                    try:
                        data_val = float(row[data_col_idx])
                        aggregated_data[label_val] = aggregated_data.get(label_val, 0) + data_val
                    except (ValueError, TypeError):
                        continue
                current_app.logger.debug(f"CHART_UTILS_BAR: 바차트 집계 결과 ({label_col_name}, {data_col_name}): {aggregated_data}")
                
                if len(aggregated_data) > 0:
                    agg_labels = list(aggregated_data.keys())
                    agg_data_values = list(aggregated_data.values())
                    chart_title = f"{label_col_korean_name}별 {data_col_korean_name}"
                    chart_config = {
                        "type": "bar",
                        "data": {
                            "labels": agg_labels,
                            "datasets": [{
                                "label": data_col_korean_name,
                                "data": agg_data_values,
                                "backgroundColor": _get_chart_colors(len(agg_labels), CHART_BACKGROUND_COLORS),
                                "borderColor": _get_chart_colors(len(agg_labels), CHART_BORDER_COLORS),
                                "borderWidth": 1
                            }]
                        },
                        "options": {
                            "responsive": True,
                            "maintainAspectRatio": False,
                            "scales": {"y": {"beginAtZero": True}},
                            "plugins": {
                                "legend": {"display": True, "position": 'top'},
                                "title": {"display": True, "text": chart_title}
                            }
                        }
                    }
                    current_app.logger.debug(f"CHART_UTILS_BAR: Aggregated Bar chart config generated with {len(agg_labels)} categories. Label: {label_col_name}, Data: {data_col_name}")
                    current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
                    return chart_config, chart_notice # Pass along notice if it was set by pie chart
                else:
                    current_app.logger.debug("CHART_UTILS_BAR: 집계 후 데이터가 없어 바차트를 생성할 수 없습니다.")
            else:
                current_app.logger.debug(f"CHART_UTILS_BAR: 적절한 데이터 컬럼을 찾지 못했습니다. 컬럼: {column_names}. 바차트 생성 불가.")

    # Fallback if pie chart was requested but couldn't be generated (e.g. no data, or only 1 item and bar also failed)
    if requested_pie_chart and not chart_config:
        current_app.logger.debug("CHART_UTILS_PIE: 파이 차트 요청되었으나 생성되지 못했고 바차트로도 대체되지 못함.")
        return None, chart_notice # Return any notice that might have been set

    # 3. 분포/히스토그램: qty 값의 분포 (기존 로직 유지하되, data_col_name 찾기 개선)
    if any(keyword in question_lower for keyword in ["분포", "분포그래프", "분포 차트", "히스토그램", "histogram", "distribution"]):
        current_app.logger.debug(f"CHART_UTILS_HIST: 히스토그램/분포 조건 진입, 컬럼: {column_names}")
        data_col_name_hist = find_chart_data_column(column_names, rows) # Find any numeric column

        if data_col_name_hist:
            data_col_idx = column_names.index(data_col_name_hist)
            data_col_korean_name_hist = get_korean_col_name_for_chart(data_col_name_hist, column_name_korean_map)
            qty_values = []
            for row in rows:
                try:
                    qty_values.append(float(row[data_col_idx]))
                except (ValueError, TypeError):
                    continue
            if len(qty_values) > 1: # Need at least 2 values for a meaningful histogram
                import numpy as np
                counts, bins = np.histogram(qty_values, bins='auto')
                labels = [f'{int(bins[i])}~{int(bins[i+1])}' for i in range(len(bins)-1)]
                chart_config = {
                    "type": "bar", # Histogram is a type of bar chart
                    "data": {
                        "labels": labels, # Corrected: Use histogram bin labels
                        "datasets": [{
                            "label": data_col_korean_name_hist,
                            "data": counts.tolist(),
                            "backgroundColor": _get_chart_colors(len(labels), CHART_BACKGROUND_COLORS), # Corrected
                            "borderColor": _get_chart_colors(len(labels), CHART_BORDER_COLORS), # Corrected
                            "borderWidth": 1
                        }]
                    },
                    "options": {
                        "responsive": True,
                        "maintainAspectRatio": False,
                        "plugins": {
                            "legend": {"display": True, "position": 'top'},
                            "title": {"display": True, "text": f"{data_col_korean_name_hist} 분포(히스토그램)"}
                        }
                    }
                }
                current_app.logger.debug(f"CHART_UTILS_HIST: Histogram chart config generated for column '{data_col_name_hist}'.")
                current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
                return chart_config, None
            else:
                current_app.logger.debug("CHART_UTILS_HIST: Not enough data for histogram.")
        else:
            current_app.logger.debug(f"CHART_UTILS_HIST: 적절한 데이터 컬럼({data_col_name_hist})을 찾지 못했거나 데이터가 없습니다. 히스토그램 생성 불가.")

    # 4. 라인차트: indat별 qty 추이 (기존 라인차트 로직)
    if not chart_config and not requested_pie_chart and not requested_bar_chart and num_cols >= 2 and num_rows > 1:
        current_app.logger.debug("CHART_UTILS_LINE: Pie/Bar chart not generated or not applicable. Checking for line chart.")
        date_col_idx, numeric_col_idx = -1, -1
        date_col_name_actual, numeric_col_name_actual = "", ""
        known_date_cols_lower = {"indat", "jego_ymd", "orddate", "reqdat", "otdat", "proddat"}

        for i, col_name_orig in enumerate(column_names):
            col_name_lower = col_name_orig.lower()
            if date_col_idx == -1 and col_name_lower in known_date_cols_lower:
                try: 
                    if isinstance(rows[0][i], str) and len(rows[0][i]) == 8 and rows[0][i].isdigit():
                        datetime.datetime.strptime(rows[0][i], "%Y%m%d") 
                        current_app.logger.debug(f"CHART_UTILS_LINE: Potential date column found: '{col_name_orig}' at index {i}")
                        date_col_idx = i
                        date_col_name_actual = col_name_orig
                except ValueError:
                    current_app.logger.debug(f"CHART_UTILS_LINE: Column '{col_name_orig}' matched known date names but format is not YYYYMMDD string.")
                    pass
            if numeric_col_idx == -1 and (date_col_idx == -1 or i != date_col_idx):
                 if isinstance(rows[0][i], (int, float, decimal.Decimal)) and all(isinstance(row[i], (int, float, decimal.Decimal)) for row in rows):
                    current_app.logger.debug(f"CHART_UTILS_LINE: Potential numeric column found: '{col_name_orig}' at index {i}")
                    numeric_col_idx = i
                    numeric_col_name_actual = col_name_orig

        if date_col_idx != -1 and numeric_col_idx != -1: # A specific date column and a numeric column were found
            current_app.logger.debug(f"CHART_UTILS_LINE: Attempting line chart. Date Col='{date_col_name_actual}', Numeric Col='{numeric_col_name_actual}'")
            try:
                chart_points = []
                for row in rows:
                    date_str = str(row[date_col_idx])
                    numeric_val = float(row[numeric_col_idx])
                    if len(date_str) == 8 and date_str.isdigit():
                        try:
                            dt_obj = datetime.datetime.strptime(date_str, "%Y%m%d")
                            chart_points.append((dt_obj, numeric_val))
                        except ValueError:
                            current_app.logger.debug(f"CHART_UTILS_LINE: Skipping row due to date parse error: date_str='{date_str}'")
                            continue
                if len(chart_points) > 1:
                    chart_points.sort(key=lambda x: x[0]) 
                    labels = [point[0].strftime("%Y-%m-%d") for point in chart_points]
                    data_values = [point[1] for point in chart_points] # numeric_col_name_actual is the original English name
                    dataset_label = get_korean_col_name_for_chart(numeric_col_name_actual, column_name_korean_map)
                    date_col_korean_label = column_name_korean_map.get(date_col_name_actual.lower(), date_col_name_actual.capitalize())
                    chart_title = f"{date_col_korean_label}별 {dataset_label} 추이"
                    chart_config = {
                        "type": "line",
                        "data": {"labels": labels, "datasets": [{"label": dataset_label, "data": data_values, "fill": False, "borderColor": 'rgb(75, 192, 192)', "tension": 0.1}]},
                        "options": {
                            "responsive": True, "maintainAspectRatio": False,
                            "scales": {"y": {"beginAtZero": True}},
                            "plugins": {"legend": {"display": True, "position": 'top'}, "title": {"display": True, "text": chart_title}}
                        }
                    }
                    current_app.logger.debug(f"CHART_UTILS_LINE: Line chart config generated for date col '{date_col_name_actual}' and numeric col '{numeric_col_name_actual}'.")
                    current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
                else:
                    current_app.logger.debug(f"CHART_UTILS_LINE: Not enough valid data points ({len(chart_points)}) for line chart after parsing.")
            except Exception as e:
                current_app.logger.error(f"CHART_UTILS_LINE: Error during line chart data prep: {e}", exc_info=True)
                chart_config = None

    # 누적차트: 누적합 컬럼 자동 인식, 없으면 qty 누적합 직접 계산
    if any(keyword in question_lower for keyword in ["누적", "누적차트", "누적 그래프", "누적합", "cumsum", "running"]):
        current_app.logger.debug(f"CHART_UTILS_CUM: 누적차트 조건 진입, 컬럼: {column_names}")
        cum_col_candidates = [col for col in column_names if any(x in col.lower() for x in ['running', '누적', 'cumsum'])]
        date_col_candidates = [col for col in column_names if col.lower() in ['indat', 'jego_ymd', 'orddate', 'reqdat', 'otdat', 'proddat']]
        qty_col = 'qty' if 'qty' in column_names else None
        if cum_col_candidates and date_col_candidates:
            cum_col_name = cum_col_candidates[0]
            date_col_name = date_col_candidates[0]
            cum_col_idx = column_names.index(cum_col_name)
            date_col_idx = column_names.index(date_col_name)
            labels = [str(row[date_col_idx]) for row in rows] # Assuming date is already formatted or string
            data_values = [float(row[cum_col_idx]) for row in rows] # Assuming numeric
            
            cum_col_korean = get_korean_col_name_for_chart(cum_col_name, column_name_korean_map)
            date_col_korean = column_name_korean_map.get(date_col_name.lower(), date_col_name)
            chart_title = f"{date_col_korean}별 {cum_col_korean} (누적)"
            chart_config = {
                "type": "line",
                "data": {
                    "labels": labels,
                    "datasets": [{
                        "label": column_name_korean_map.get(cum_col.lower(), cum_col),
                        "data": data_values,
                        "fill": True, # Often good for cumulative
                        "borderColor": 'rgb(255, 99, 132)',
                        "tension": 0.1
                    }]
                },
                "options": {
                    "responsive": True,
                    "maintainAspectRatio": False,
                    "scales": {"y": {"beginAtZero": True}},
                    "plugins": {
                        "legend": {"display": True, "position": 'top'},
                        "title": {"display": True, "text": chart_title}
                    }
                }
            }
            current_app.logger.debug(f"CHART_UTILS_CUM: 누적 라인차트 config generated.")
            current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
            return chart_config, None
        elif qty_col and date_col_candidates:
            date_col_name = date_col_candidates[0]
            qty_col_name = qty_col # This is 'qty'
            date_col_idx = column_names.index(date_col_name)
            qty_col_idx = column_names.index(qty_col_name)
            # 날짜별 qty 합산
            date_qty_map = {} # Key: date_val (string), Value: sum_qty_for_date (float)
            for row in rows:
                date_val = str(row[date_col_idx])
                try:
                    qty_val = float(row[qty_col_idx])
                except (ValueError, TypeError):
                    continue
                date_qty_map[date_val] = date_qty_map.get(date_val, 0) + qty_val
            
            # 날짜 오름차순 정렬 후 누적합 계산
            # Attempt to sort dates if they are in YYYYMMDD format
            try:
                sorted_dates = sorted(date_qty_map.keys(), key=lambda d: datetime.datetime.strptime(d, "%Y%m%d") if len(d)==8 and d.isdigit() else d)
            except ValueError: # If not all dates are YYYYMMDD, sort as string
                sorted_dates = sorted(date_qty_map.keys())

            labels = []
            data_values = []
            running_total = 0
            for date_val in sorted_dates:
                running_total += date_qty_map[date_val]
                # Format date for display if YYYYMMDD
                display_date = datetime.datetime.strptime(date_val, "%Y%m%d").strftime("%Y-%m-%d") if len(date_val)==8 and date_val.isdigit() else date_val
                labels.append(display_date)
                data_values.append(running_total)

            date_col_korean = column_name_korean_map.get(date_col_name.lower(), date_col_name)
            qty_korean = get_korean_col_name_for_chart(qty_col_name, column_name_korean_map)
            chart_title = f"{date_col_korean}별 누적 {qty_korean}"
            chart_config = {
                "type": "line",
                "data": {
                    "labels": labels,
                    "datasets": [{
                        "label": "누적 수량",
                        "data": data_values,
                        "fill": True, # Often good for cumulative
                        "borderColor": 'rgb(255, 99, 132)',
                        "tension": 0.1,
                    }]
                },
                "options": {
                    "responsive": True,
                    "maintainAspectRatio": False,
                    "scales": {"y": {"beginAtZero": True}},
                    "plugins": {
                        "legend": {"display": True, "position": 'top'},
                        "title": {"display": True, "text": chart_title}
                    }
                }
            }
            current_app.logger.debug(f"CHART_UTILS_CUM: 날짜별 합산 후 누적합 라인차트 config generated.")
            current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
            return chart_config, None
        else:
            current_app.logger.debug("CHART_UTILS_CUM: 누적합/날짜 컬럼 없음, 누적차트 생성 불가")

    # 스택차트(누적 막대그래프): 날짜별, 품명별 qty 집계
    if any(keyword in question_lower for keyword in ["스택", "스택차트", "스택 그래프", "누적바", "누적 바", "누적 막대", "stack", "stacked"]):
        current_app.logger.debug(f"CHART_UTILS_STACK: 스택차트 조건 진입, 컬럼: {column_names}")
        date_col_name_stack = next((col for col in column_names if col.lower() in {"indat", "jego_ymd", "orddate", "reqdat", "otdat", "proddat"}), None)
        group_col_name_stack = 'jpname' if 'jpname' in column_names else None # Group by product name
        data_col_name_stack = find_chart_data_column(column_names, rows, group_col_name_stack) # Find qty-like column

        if date_col_name_stack and group_col_name_stack and data_col_name_stack:
            date_col_idx = column_names.index(date_col_name_stack)
            group_col_idx = column_names.index(group_col_name_stack)
            qty_col_idx = column_names.index(data_col_name_stack)
            # 날짜, 품명별 qty 집계
            data_map = {}
            group_set = set()
            date_set = set()
            for row in rows:
                date_val = str(row[date_col_idx])
                group_val = str(row[group_col_idx])
                try: # data_col_name_stack is qty-like
                    qty_val = float(row[qty_col_idx])
                except (ValueError, TypeError):
                    continue
                data_map.setdefault(date_val, {}).setdefault(group_val, 0)
                data_map[date_val][group_val] += qty_val
                group_set.add(group_val)
                date_set.add(date_val)
            
            try: # Sort dates if YYYYMMDD
                sorted_dates_raw = sorted(date_set, key=lambda d: datetime.datetime.strptime(d, "%Y%m%d") if len(d)==8 and d.isdigit() else d)
            except ValueError:
                sorted_dates_raw = sorted(date_set)
            
            sorted_dates_display = [datetime.datetime.strptime(d, "%Y%m%d").strftime("%Y-%m-%d") if len(d)==8 and d.isdigit() else d for d in sorted_dates_raw]
            sorted_groups = sorted(group_set)

            # 각 그룹별로 날짜별 qty 리스트 생성
            datasets = []
            for i, group in enumerate(sorted_groups):
                data = []
                for date in sorted_dates_raw: # Use raw dates for map lookup
                    data.append(data_map.get(date, {}).get(group, 0))
                datasets.append({
                    "label": group,
                    "data": data,
                    "backgroundColor": CHART_BACKGROUND_COLORS[i % len(CHART_BACKGROUND_COLORS)],
                    "borderColor": CHART_BORDER_COLORS[i % len(CHART_BORDER_COLORS)],
                    "borderWidth": 1
                })
            
            date_korean_stack = column_name_korean_map.get(date_col_name_stack.lower(), date_col_name_stack)
            group_korean_stack = column_name_korean_map.get(group_col_name_stack.lower(), group_col_name_stack)
            data_korean_stack = get_korean_col_name_for_chart(data_col_name_stack, column_name_korean_map)
            chart_title = f"{date_korean_stack}별 {group_korean_stack}별 {data_korean_stack} (스택차트)"
            chart_config = {
                "type": "bar",
                "data": {
                    "labels": sorted_dates_display, # Use display dates for labels
                    "datasets": datasets
                },
                "options": {
                    "responsive": True,
                    "maintainAspectRatio": False,
                    "scales": {
                        "x": {"stacked": True},
                        "y": {"stacked": True, "beginAtZero": True}
                    },
                    "plugins": {
                        "legend": {"display": True, "position": 'top'},
                        "title": {"display": True, "text": chart_title}
                    }
                }
            }
            current_app.logger.debug(f"CHART_UTILS_STACK: 스택 바차트 config generated.")
            current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
            return chart_config, None
        else:
            current_app.logger.debug(f"CHART_UTILS_STACK: 필수 컬럼(날짜: {date_col_name_stack}, 그룹: {group_col_name_stack}, 데이터: {data_col_name_stack}) 부족으로 스택차트 생성 불가")

    # --- [수정] 단순 시각화 요청(예: "그래프 그려줘")에서 컬럼 자동 매핑 우선순위 강화 ---
    if requested_any_chart and not chart_config:
        current_app.logger.debug(f"CHART_UTILS_DEFAULT_FALLBACK_BAR: No specific chart type made. Attempting general default bar chart. Columns: {column_names}")

        # 1. 날짜+수량 → 라인차트
        date_col = next((col for col in column_names if col.lower() in {"indat", "jego_ymd", "orddate", "reqdat", "otdat", "proddat"}), None)
        qty_col = next((col for col in column_names if "qty" in col.lower()), None)
        if date_col and qty_col:
            date_col_idx = column_names.index(date_col)
            qty_col_idx = column_names.index(qty_col)
            try:
                chart_points = []
                for row in rows:
                    date_str = str(row[date_col_idx])
                    qty_val = float(row[qty_col_idx])
                    if len(date_str) == 8 and date_str.isdigit():
                        dt_obj = datetime.datetime.strptime(date_str, "%Y%m%d")
                        chart_points.append((dt_obj, qty_val))
                if len(chart_points) > 1:
                    chart_points.sort(key=lambda x: x[0])
                    labels = [point[0].strftime("%Y-%m-%d") for point in chart_points]
                    data_values = [point[1] for point in chart_points]
                    dataset_label = get_korean_col_name_for_chart(qty_col, column_name_korean_map)
                    date_col_korean_label = column_name_korean_map.get(date_col.lower(), date_col.capitalize())
                    chart_title = f"{date_col_korean_label}별 {dataset_label} 추이"
                    chart_config = {
                        "type": "line",
                        "data": {"labels": labels, "datasets": [{"label": dataset_label, "data": data_values, "fill": False, "borderColor": 'rgb(75, 192, 192)', "tension": 0.1}]},
                        "options": {
                            "responsive": True, "maintainAspectRatio": False,
                            "scales": {"y": {"beginAtZero": True}},
                            "plugins": {"legend": {"display": True, "position": 'top'}, "title": {"display": True, "text": chart_title}}
                        }
                    }
                    current_app.logger.debug(f"CHART_UTILS_DEFAULT_FALLBACK_BAR: Line chart generated for date col '{date_col}' and qty col '{qty_col}'.")
                    return chart_config, None
            except Exception as e:
                current_app.logger.error(f"CHART_UTILS_DEFAULT_FALLBACK_BAR: Error during line chart fallback: {e}", exc_info=True)

        # 2. 품명+수량 → 바차트
        label_col = None
        if 'jpname' in column_names:
            label_col = 'jpname'
        elif 'item_code' in column_names:
            label_col = 'item_code'
        else:
            for col_name_iter in column_names:
                if rows and isinstance(rows[0][column_names.index(col_name_iter)], str):
                    label_col = col_name_iter
                    break

        if label_col and qty_col:
            label_col_idx = column_names.index(label_col)
            qty_col_idx = column_names.index(qty_col)
            aggregated_data = {}
            for row_item in rows:
                label_val = str(row_item[label_col_idx])
                try:
                    data_val = float(row_item[qty_col_idx])
                    aggregated_data[label_val] = aggregated_data.get(label_val, 0) + data_val
                except (ValueError, TypeError):
                    continue
            if len(aggregated_data) > 0:
                agg_labels = list(aggregated_data.keys())
                agg_data_values = list(aggregated_data.values())
                chart_title = f"{column_name_korean_map.get(label_col.lower(), label_col)}별 {get_korean_col_name_for_chart(qty_col, column_name_korean_map)}"
                chart_config = {
                    "type": "bar",
                    "data": { "labels": agg_labels, "datasets": [{"label": get_korean_col_name_for_chart(qty_col, column_name_korean_map), "data": agg_data_values, "backgroundColor": _get_chart_colors(len(agg_labels), CHART_BACKGROUND_COLORS), "borderColor": _get_chart_colors(len(agg_labels), CHART_BORDER_COLORS), "borderWidth": 1}]},
                    "options": {"responsive": True, "maintainAspectRatio": False, "scales": {"y": {"beginAtZero": True}}, "plugins": {"legend": {"display": True, "position": 'top'}, "title": {"display": True, "text": chart_title}}}
                }
                current_app.logger.debug(f"CHART_UTILS_DEFAULT_FALLBACK_BAR: Default fallback Bar chart generated with {len(agg_labels)} categories. Label: {label_col}, Data: {qty_col}")
                return chart_config, None

        current_app.logger.debug(f"CHART_UTILS_DEFAULT_FALLBACK_BAR: Could not find suitable data/label column for default chart. Columns: {column_names}")

    if chart_config:
        current_app.logger.debug(f"CHART_UTILS: 최종 반환 차트 타입: {chart_config['type']}")
    else:
        current_app.logger.debug("CHART_UTILS: No suitable chart config generated (neither pie, bar, nor line).")

    # [수정] chart_notice_prev_result가 있으면 chart_notice와 별도로 반환
    return chart_config, chart_notice_prev_result or chart_notice