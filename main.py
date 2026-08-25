import os
import time
import threading
from datetime import datetime, timedelta
import flet as ft
from db_manager import db_service
from auth_manager import load_saved_login, save_login_state, authenticate

def main(page: ft.Page):
    page.title = "Optibook-IMS Mobile"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 10
    page.window_width = 430
    page.window_height = 820

    current_user = {"info": None}
    active_tab = [0]  # 0: 검수, 1: 목록, 2: 내역, 3: 집계
    selected_isbns = set()
    is_exporting = [False]  # 엑셀 추출 중복 클릭 방지 플래그

    network_icon = ft.Icon(icon=ft.Icons.WIFI, color="#2E7D32")
    user_label = ft.Text("", size=12, color="#FFFFFF")

    # ==========================================
    # 공통: 엑셀 내보내기 및 3중 피드백
    # ==========================================
    def execute_excel_export(target_books: list, vendor_label: str, trigger_btn_text: ft.Text = None):
        if is_exporting[0]:
            return
        is_exporting[0] = True

        if trigger_btn_text:
            trigger_btn_text.value = "저장 중..."
            page.update()

        if not target_books:
            is_exporting[0] = False
            if trigger_btn_text:
                trigger_btn_text.value = "검수서류 엑셀 추출"
            
            def close_empty(e):
                alert_empty.open = False
                page.update()

            alert_empty = ft.AlertDialog(
                title=ft.Text("알림", weight=ft.FontWeight.BOLD),
                content=ft.Text("내보낼 도서 데이터가 없습니다."),
                actions=[ft.TextButton(content=ft.Text("확인"), on_click=close_empty)]
            )
            page.dialog = alert_empty
            alert_empty.open = True
            page.update()
            return

        # 엑셀 파일 생성
        file_path = db_service.export_books_to_excel(target_books, vendor_label)
        file_name = os.path.basename(file_path)
        intake_count = len([b for b in target_books if b.get('상태') == '입고'])

        # 버튼 완료 피드백
        if trigger_btn_text:
            trigger_btn_text.value = "✅ 저장 완료!"
            page.update()

        def close_success(e):
            alert_success.open = False
            page.update()

        def open_file_action(e):
            try:
                os.startfile(file_path)
            except Exception:
                pass
            alert_success.open = False
            page.update()

        # 1. 화면 중앙 팝업 다이얼로그
        alert_success = ft.AlertDialog(
            title=ft.Text("✅ 엑셀 내보내기 완료", weight=ft.FontWeight.BOLD, color="#2E7D32"),
            content=ft.Column([
                ft.Text(f"납품처: [{vendor_label}]", weight=ft.FontWeight.BOLD, color="#1565C0"),
                ft.Text(f"총 {len(target_books)}건 (입고완료: {intake_count}건)", size=13),
                ft.Text(f"파일명: {file_name}", size=12, color="#555555"),
                ft.Text(f"저장경로:\n{file_path}", size=11, color="#757575"),
            ], spacing=6, tight=True),
            actions=[
                ft.Container(
                    content=ft.Text("파일 열기", color="#FFFFFF", size=13, weight=ft.FontWeight.BOLD),
                    bgcolor="#1565C0",
                    padding=ft.Padding(12, 6, 12, 6),
                    border_radius=4,
                    ink=True,
                    on_click=open_file_action
                ),
                ft.TextButton(content=ft.Text("닫기"), on_click=close_success)
            ]
        )
        page.dialog = alert_success
        alert_success.open = True

        # 2. 하단 스낵바 알림 동시 출력
        page.snack_bar = ft.SnackBar(
            content=ft.Text(f"엑셀 저장 완료: {file_name} ({len(target_books)}건)"),
            bgcolor="#2E7D32",
            duration=3000
        )
        page.snack_bar.open = True
        page.update()

        # 2초 후 플래그 및 버튼 텍스트 원상복구
        def reset_btn():
            time.sleep(2)
            is_exporting[0] = False
            if trigger_btn_text:
                trigger_btn_text.value = "검수서류 엑셀 추출" if "추출" in trigger_btn_text.value or "완료" in trigger_btn_text.value else "검수서류"
                try:
                    page.update()
                except Exception:
                    pass

        threading.Thread(target=reset_btn, daemon=True).start()

    # ==========================================
    # 탭 1: 검수 화면 컨트롤
    # ==========================================
    inspect_vendor_filter = ft.Dropdown(label="작업 납품처 고정", width=390, value="전체")
    scan_result_title = ft.Text("바코드를 스캔하세요", size=17, weight=ft.FontWeight.BOLD)
    scan_result_info = ft.Text("ISBN: - | 납품처: -", size=13, color="#555555")
    scan_badge_text = ft.Text("대기 중", color="#FFFFFF", size=12, weight=ft.FontWeight.BOLD)
    scan_badge = ft.Container(
        content=scan_badge_text,
        bgcolor="#757575",
        padding=ft.Padding(10, 4, 10, 4),
        border_radius=6
    )
    recent_list_view = ft.ListView(expand=True, spacing=8)

    def update_recent_list():
        recent_list_view.controls.clear()
        for book in db_service.recent_scans[:15]:
            recent_list_view.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(book.get('도서명', ''), size=14, weight=ft.FontWeight.BOLD, max_lines=1, overflow="ellipsis"),
                            ft.Text(f"[{book.get('납품처', '')}] ISBN: {book.get('ISBN_Clean', '')} | {book.get('입고일시', '')}", size=11, color="#666666")
                        ], expand=True),
                        ft.Container(
                            content=ft.Text("입고", color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD),
                            bgcolor="#2E7D32",
                            padding=ft.Padding(6, 2, 6, 2),
                            border_radius=4
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=8,
                    bgcolor="#F5F5F5",
                    border_radius=6
                )
            )

    def on_barcode_scanned(e):
        isbn = e.control.value.strip()
        e.control.value = ""
        if not isbn:
            return

        target_vendor = inspect_vendor_filter.value or "전체"
        status, book, is_online = db_service.process_barcode_scan(isbn, target_vendor)

        network_icon.icon = ft.Icons.WIFI if is_online else ft.Icons.WIFI_OFF
        network_icon.color = "#2E7D32" if is_online else "#C62828"

        if status == "SUCCESS":
            scan_result_title.value = book.get('도서명', '')
            scan_result_info.value = f"[{book.get('납품처', '')}] 정가: {book.get('정가', '')}원 | ISBN: {book.get('ISBN_Clean', '')}"
            scan_badge.bgcolor = "#2E7D32"
            scan_badge_text.value = "입고 완료 (정상)"
            update_recent_list()
        elif status == "ALREADY_IN":
            scan_result_title.value = book.get('도서명', '')
            scan_result_info.value = f"[{book.get('납품처', '')}] 이미 입고 완료된 도서입니다."
            scan_badge.bgcolor = "#F57C00"
            scan_badge_text.value = "기입고 도서"
        elif status == "WRONG_VENDOR":
            scan_result_title.value = "납품처 불일치 경고"
            scan_result_info.value = f"현재 설정[{target_vendor}] ≠ 실제 도서[{book.get('target', '')}]"
            scan_badge.bgcolor = "#D32F2F"
            scan_badge_text.value = "타 납품처 도서"
        else:
            scan_result_title.value = "미등록 도서 (불일치)"
            scan_result_info.value = f"입력된 ISBN: {isbn}"
            scan_badge.bgcolor = "#C62828"
            scan_badge_text.value = "스캔 실패"

        page.update()

    barcode_field = ft.TextField(
        label="ISBN 바코드 스캔 / 수기 입력",
        autofocus=True,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_submit=on_barcode_scanned
    )

    def build_inspect_view():
        vendors = db_service.get_vendor_list()
        inspect_vendor_filter.options = [ft.dropdown.Option(v) for v in vendors]
        return ft.Column([
            inspect_vendor_filter,
            barcode_field,
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        scan_result_title,
                        scan_result_info,
                        ft.Row([scan_badge], alignment=ft.MainAxisAlignment.END)
                    ], spacing=6),
                    padding=12
                )
            ),
            ft.Text("최근 입고 완료 내역", size=14, weight=ft.FontWeight.BOLD, color="#1565C0"),
            recent_list_view
        ], expand=True, spacing=10)

    # ==========================================
    # 탭 2: 목록 화면 컨트롤 & 엑셀 내보내기
    # ==========================================
    list_search_field = ft.TextField(label="도서명/ISBN 검색", expand=True, on_submit=lambda e: render_book_list())
    list_vendor_dropdown = ft.Dropdown(label="납품처", width=140, value="전체")
    list_status_dropdown = ft.Dropdown(
        label="상태", width=100, value="전체",
        options=[ft.dropdown.Option("전체"), ft.dropdown.Option("입고"), ft.dropdown.Option("미입고")]
    )
    select_all_chk = ft.Checkbox(label="전체 선택", value=False)
    btn_export_text = ft.Text("검수서류 엑셀 추출", color="#FFFFFF", size=12, weight=ft.FontWeight.BOLD)
    btn_export_excel = ft.Container()
    book_list_container = ft.ListView(expand=True, spacing=8)
    current_filtered_books = []

    def toggle_select_all(e):
        is_checked = select_all_chk.value
        selected_isbns.clear()
        if is_checked:
            for b in current_filtered_books:
                selected_isbns.add(b.get("ISBN_Clean", ""))
        render_book_list(refresh_data=False)

    select_all_chk.on_change = toggle_select_all

    def handle_list_tab_export(e):
        target_books = []
        if selected_isbns:
            target_books = [b for b in current_filtered_books if b.get("ISBN_Clean", "") in selected_isbns]
        else:
            target_books = current_filtered_books

        vendor_name = list_vendor_dropdown.value or "전체"
        execute_excel_export(target_books, vendor_name, btn_export_text)

    btn_export_excel.content = ft.Row([
        ft.Icon(icon=ft.Icons.FILE_DOWNLOAD, color="#FFFFFF", size=16),
        btn_export_text
    ], alignment=ft.MainAxisAlignment.CENTER)
    btn_export_excel.bgcolor = "#2E7D32"
    btn_export_excel.padding = ft.Padding(12, 8, 12, 8)
    btn_export_excel.border_radius = 6
    btn_export_excel.ink = True
    btn_export_excel.on_click = handle_list_tab_export

    def toggle_book_select(isbn, checked):
        if checked:
            selected_isbns.add(isbn)
        else:
            selected_isbns.discard(isbn)
        select_all_chk.value = (len(selected_isbns) == len(current_filtered_books) and len(current_filtered_books) > 0)
        page.update()

    def render_book_list(refresh_data=True):
        nonlocal current_filtered_books
        if refresh_data:
            v = list_vendor_dropdown.value or "전체"
            s = list_status_dropdown.value or "전체"
            q = list_search_field.value or ""
            current_filtered_books = db_service.get_filtered_books(v, s, q)

        book_list_container.controls.clear()

        for b in current_filtered_books:
            isbn = b.get('ISBN_Clean', '')
            st = b.get('상태', '미입고')
            st_color = "#2E7D32" if st == "입고" else "#C62828"
            is_checked = isbn in selected_isbns

            chk = ft.Checkbox(value=is_checked)
            chk.on_change = lambda e, code=isbn: toggle_book_select(code, e.control.value)

            book_list_container.controls.append(
                ft.Container(
                    content=ft.Row([
                        chk,
                        ft.Column([
                            ft.Row([
                                ft.Text(f"#{b.get('순번', '')} {b.get('도서명', '')}", size=14, weight=ft.FontWeight.BOLD, expand=True, max_lines=1, overflow="ellipsis"),
                                ft.Container(content=ft.Text(st, color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD), bgcolor=st_color, padding=ft.Padding(6, 2, 6, 2), border_radius=4)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Text(f"납품처: {b.get('납품처', '')} | 저자: {b.get('저자', '')} | 출판사: {b.get('출판사', '')}", size=11, color="#666666"),
                            ft.Text(f"ISBN: {isbn} | 정가: {b.get('정가', '')}원 | 권수: {b.get('권수', '1')}권", size=11, color="#444444")
                        ], expand=True, spacing=3)
                    ], alignment=ft.MainAxisAlignment.START),
                    padding=8,
                    bgcolor="#F9F9F9",
                    border_radius=8
                )
            )
        page.update()

    list_vendor_dropdown.on_change = lambda e: (selected_isbns.clear(), render_book_list())
    list_status_dropdown.on_change = lambda e: (selected_isbns.clear(), render_book_list())

    def build_list_view():
        vendors = db_service.get_vendor_list()
        list_vendor_dropdown.options = [ft.dropdown.Option(v) for v in vendors]
        return ft.Column([
            ft.Row([list_vendor_dropdown, list_status_dropdown]),
            ft.Row([
                list_search_field,
                ft.Container(
                    content=ft.Icon(icon=ft.Icons.SEARCH, color="#FFFFFF"),
                    bgcolor="#1565C0",
                    padding=10,
                    border_radius=6,
                    ink=True,
                    on_click=lambda e: render_book_list()
                )
            ]),
            ft.Row([
                select_all_chk,
                btn_export_excel
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            book_list_container
        ], expand=True, spacing=10)

    # ==========================================
    # 탭 3: 내역 화면 컨트롤
    # ==========================================
    history_date_input = ft.TextField(
        value=datetime.now().strftime("%Y-%m-%d"),
        label="입고 일자 (YYYY-MM-DD)",
        width=160,
        text_align=ft.TextAlign.CENTER
    )
    history_stat_text = ft.Text("입고 건수: 0권 | 총액: 0원", size=13, weight=ft.FontWeight.BOLD, color="#1565C0")
    history_list_container = ft.ListView(expand=True, spacing=8)

    def render_history_list(target_date=None):
        if not target_date:
            target_date = history_date_input.value.strip() or datetime.now().strftime("%Y-%m-%d")
        history_date_input.value = target_date

        books = db_service.get_history_books(target_date)
        history_list_container.controls.clear()

        total_price = 0
        for b in books:
            try:
                total_price += int(float(b.get('정가', 0)))
            except Exception:
                pass

        history_stat_text.value = f"입고 건수: {len(books):,}권 | 총액: {total_price:,}원"

        if not books:
            history_list_container.controls.append(
                ft.Container(
                    content=ft.Text(f"[{target_date}] 입고 내역이 없습니다.", color="#757575", size=14),
                    alignment=ft.Alignment(0, 0),
                    padding=20
                )
            )
        else:
            for idx, b in enumerate(books, start=1):
                intake_time = b.get('입고일시', '')
                history_list_container.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(f"#{idx} {b.get('도서명', '')}", size=14, weight=ft.FontWeight.BOLD, expand=True, max_lines=1, overflow="ellipsis"),
                                ft.Container(
                                    content=ft.Text(f"⏰ {intake_time[11:] if len(intake_time) >= 16 else intake_time}", color="#1565C0", size=11, weight=ft.FontWeight.BOLD),
                                    bgcolor="#E3F2FD",
                                    padding=ft.Padding(6, 2, 6, 2),
                                    border_radius=4
                                )
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Text(f"납품처: {b.get('납품처', '')} | 거래처: {b.get('거래처', '')}", size=11, color="#666666"),
                            ft.Row([
                                ft.Text(f"ISBN: {b.get('ISBN_Clean', '')}", size=11, color="#444444"),
                                ft.Text(f"정가: {b.get('정가', '')}원 | {b.get('권수', '1')}권", size=11, weight=ft.FontWeight.BOLD, color="#2E7D32")
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                        ], spacing=4),
                        padding=10,
                        bgcolor="#F9F9F9",
                        border_radius=8
                    )
                )
        page.update()

    def set_history_today(e):
        render_history_list(datetime.now().strftime("%Y-%m-%d"))

    def set_history_yesterday(e):
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        render_history_list(yesterday)

    def build_history_view():
        return ft.Column([
            ft.Row([
                history_date_input,
                ft.Container(
                    content=ft.Text("오늘", color="#FFFFFF", size=12, weight=ft.FontWeight.BOLD),
                    bgcolor="#1565C0",
                    padding=ft.Padding(10, 10, 10, 10),
                    border_radius=6,
                    ink=True,
                    on_click=set_history_today
                ),
                ft.Container(
                    content=ft.Text("어제", color="#333333", size=12, weight=ft.FontWeight.BOLD),
                    bgcolor="#E0E0E0",
                    padding=ft.Padding(10, 10, 10, 10),
                    border_radius=6,
                    ink=True,
                    on_click=set_history_yesterday
                ),
                ft.Container(
                    content=ft.Icon(icon=ft.Icons.SEARCH, color="#FFFFFF"),
                    bgcolor="#2E7D32",
                    padding=8,
                    border_radius=6,
                    ink=True,
                    on_click=lambda e: render_history_list()
                )
            ], alignment=ft.MainAxisAlignment.START),
            ft.Card(
                content=ft.Container(
                    content=history_stat_text,
                    padding=10,
                    bgcolor="#E8F5E9"
                )
            ),
            history_list_container
        ], expand=True, spacing=10)

    # ==========================================
    # 집계 -> 목록 직관적 네비게이션 함수
    # ==========================================
    def navigate_to_filtered_list(vendor="전체", status="전체"):
        selected_isbns.clear()
        select_all_chk.value = False
        list_vendor_dropdown.value = vendor
        list_status_dropdown.value = status
        list_search_field.value = ""
        switch_tab(1)

    # ==========================================
    # 탭 4: 집계 화면 컨트롤
    # ==========================================
    summary_total_card = ft.Card()
    summary_vendor_list = ft.ListView(expand=True, spacing=8)

    def render_summary_view():
        data = db_service.get_summary_data()

        summary_total_card.content = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("전체 납품 집계 현황", size=15, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(icon=ft.Icons.FILE_DOWNLOAD, color="#FFFFFF", size=14),
                            ft.Text("전체 엑셀", color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD)
                        ]),
                        bgcolor="#2E7D32",
                        padding=ft.Padding(8, 4, 8, 4),
                        border_radius=4,
                        ink=True,
                        on_click=lambda e: execute_excel_export(db_service.get_filtered_books("전체"), "전체납품처")
                    )
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(color="#90CAF9", height=8),
                ft.Row([
                    ft.Container(
                        content=ft.Text(f"전체 {data['total_qty']:,}권", size=13, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                        ink=True,
                        padding=ft.Padding(6, 4, 6, 4),
                        border_radius=4,
                        on_click=lambda e: navigate_to_filtered_list("전체", "전체")
                    ),
                    ft.Container(
                        content=ft.Text(f"입고 {data['intake_qty']:,}권", size=13, color="#C8E6C9", weight=ft.FontWeight.BOLD),
                        ink=True,
                        padding=ft.Padding(6, 4, 6, 4),
                        border_radius=4,
                        on_click=lambda e: navigate_to_filtered_list("전체", "입고")
                    ),
                    ft.Container(
                        content=ft.Text(f"미입고 {data['pending_qty']:,}권", size=13, color="#FFCDD2", weight=ft.FontWeight.BOLD),
                        ink=True,
                        padding=ft.Padding(6, 4, 6, 4),
                        border_radius=4,
                        bgcolor="#B71C1C",
                        on_click=lambda e: navigate_to_filtered_list("전체", "미입고")
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text(f"총 정가 합계: {data['total_price']:,} 원", size=14, color="#FFFFFF", weight=ft.FontWeight.BOLD)
            ], spacing=6),
            padding=14,
            bgcolor="#1565C0",
            border_radius=8
        )

        summary_vendor_list.controls.clear()
        for v in data["vendors"]:
            v_name = v["delivery"]
            rate = int((v["intake"] / v["total"] * 100)) if v["total"] > 0 else 0

            summary_vendor_list.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(icon=ft.Icons.FOLDER_OPEN, size=16, color="#1565C0"),
                                    ft.Text(f"[{v['client']}] {v_name}", size=14, weight=ft.FontWeight.BOLD),
                                ]),
                                expand=True,
                                ink=True,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "전체")
                            ),
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(icon=ft.Icons.DESCRIPTION, color="#FFFFFF", size=12),
                                    ft.Text("검수서류", color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD)
                                ]),
                                bgcolor="#1565C0",
                                padding=ft.Padding(8, 4, 8, 4),
                                border_radius=4,
                                ink=True,
                                on_click=lambda e, name=v_name: execute_excel_export(db_service.get_filtered_books(name), name)
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.ProgressBar(value=rate / 100.0, color="#2E7D32", bgcolor="#E0E0E0"),
                        ft.Row([
                            ft.Container(
                                content=ft.Text(f"전체: {v['total']}권", size=11, color="#555555"),
                                ink=True,
                                padding=ft.Padding(4, 2, 4, 2),
                                border_radius=4,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "전체")
                            ),
                            ft.Container(
                                content=ft.Text(f"입고: {v['intake']}권", size=11, color="#2E7D32", weight=ft.FontWeight.BOLD),
                                ink=True,
                                padding=ft.Padding(6, 2, 6, 2),
                                bgcolor="#E8F5E9",
                                border_radius=4,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "입고")
                            ),
                            ft.Container(
                                content=ft.Text(f"미입고: {v['pending']}권", size=11, color="#C62828", weight=ft.FontWeight.BOLD),
                                ink=True,
                                padding=ft.Padding(6, 2, 6, 2),
                                bgcolor="#FFEBEE",
                                border_radius=4,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "미입고")
                            ),
                            ft.Text(f"{v['price']:,}원", size=11, color="#333333")
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ], spacing=6),
                    padding=12,
                    bgcolor="#F9F9F9",
                    border_radius=8
                )
            )
        page.update()

    def build_summary_view():
        return ft.Column([
            summary_total_card,
            ft.Text("납품처별 현황 ([검수서류] 클릭 시 즉시 엑셀 발행)", size=13, weight=ft.FontWeight.BOLD, color="#1565C0"),
            summary_vendor_list
        ], expand=True, spacing=10)

    # ==========================================
    # 화면 전환 및 4개 하단 네비게이션
    # ==========================================
    content_area = ft.Container(expand=True)

    def make_nav_item(idx, icon_name, label_text):
        is_active = (active_tab[0] == idx)
        active_color = "#1565C0" if is_active else "#757575"
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(icon=icon_name, size=20, color=active_color),
                    ft.Text(label_text, size=11, weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL, color=active_color)
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2
            ),
            alignment=ft.Alignment(0, 0),
            expand=True,
            padding=ft.Padding(0, 4, 0, 4),
            ink=True,
            on_click=lambda e: switch_tab(idx)
        )

    bottom_nav_bar = ft.Container(
        content=ft.Row([
            make_nav_item(0, ft.Icons.QR_CODE_SCANNER, "검수"),
            make_nav_item(1, ft.Icons.LIST_ALT, "목록"),
            make_nav_item(2, ft.Icons.HISTORY, "내역"),
            make_nav_item(3, ft.Icons.ANALYTICS, "집계"),
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
        bgcolor="#FFFFFF",
        height=55
    )

    def update_bottom_bar():
        bottom_nav_bar.content = ft.Row([
            make_nav_item(0, ft.Icons.QR_CODE_SCANNER, "검수"),
            make_nav_item(1, ft.Icons.LIST_ALT, "목록"),
            make_nav_item(2, ft.Icons.HISTORY, "내역"),
            make_nav_item(3, ft.Icons.ANALYTICS, "집계"),
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND)

    def switch_tab(index):
        active_tab[0] = index
        update_bottom_bar()
        if index == 0:
            content_area.content = build_inspect_view()
            update_recent_list()
        elif index == 1:
            content_area.content = build_list_view()
            render_book_list()
        elif index == 2:
            content_area.content = build_history_view()
            render_history_list()
        elif index == 3:
            content_area.content = build_summary_view()
            render_summary_view()
        page.update()

    def manual_sync(e):
        comp_id = current_user["info"].get("company_id", "ALL")
        is_online = db_service.load_database(comp_id)
        network_icon.icon = ft.Icons.WIFI if is_online else ft.Icons.WIFI_OFF
        network_icon.color = "#2E7D32" if is_online else "#C62828"
        switch_tab(active_tab[0])

    def show_main_screen():
        page.controls.clear()
        u = current_user["info"]
        user_label.value = f"{u.get('user_name', '')} [{u.get('company_id', '')}]"

        page.appbar = ft.AppBar(
            title=ft.Text("Optibook-IMS"),
            bgcolor="#1565C0",
            color="#FFFFFF",
            actions=[
                ft.Column([user_label], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(content=network_icon, padding=ft.Padding(4, 0, 4, 0)),
                ft.Container(
                    content=ft.Icon(icon=ft.Icons.REFRESH, color="#FFFFFF"),
                    padding=ft.Padding(0, 0, 12, 0),
                    ink=True,
                    on_click=manual_sync
                )
            ]
        )

        page.add(
            ft.Column([
                content_area,
                ft.Divider(height=1, color="#E0E0E0"),
                bottom_nav_bar
            ], expand=True, spacing=0)
        )
        switch_tab(0)

    # ==========================================
    # 로그인 화면
    # ==========================================
    saved_id, saved_pw = load_saved_login()
    id_input = ft.TextField(label="아이디", value=saved_id, width=320)
    pw_input = ft.TextField(label="비밀번호", value=saved_pw, password=True, can_reveal_password=True, width=320)
    remember_chk = ft.Checkbox(label="로그인 정보 저장", value=bool(saved_id), width=320)
    error_msg = ft.Text("", color="#C62828", size=13)

    def handle_login(e):
        uid = id_input.value.strip()
        pw = pw_input.value.strip()
        if not uid or not pw:
            error_msg.value = "아이디와 비밀번호를 모두 입력하세요."
            page.update()
            return

        success, user_info, is_online = authenticate(uid, pw)
        if success:
            save_login_state(uid, pw, remember_chk.value)
            current_user["info"] = user_info
            db_service.load_database(user_info.get("company_id", "ALL"))
            show_main_screen()
        else:
            error_msg.value = "계정 정보가 올바르지 않거나 미승인 계정입니다."
            page.update()

    login_btn = ft.Container(
        content=ft.Text("로그인", color="#FFFFFF", size=16, weight=ft.FontWeight.BOLD),
        alignment=ft.Alignment(0, 0),
        width=320,
        height=48,
        bgcolor="#1565C0",
        border_radius=8,
        ink=True,
        on_click=handle_login
    )

    page.appbar = ft.AppBar(title=ft.Text("Optibook-IMS 로그인"), bgcolor="#1565C0", color="#FFFFFF", center_title=True)
    page.add(
        ft.Column([
            ft.Container(height=20),
            ft.Icon(icon=ft.Icons.MENU_BOOK, size=64, color="#1565C0"),
            ft.Text("Optibook-IMS Mobile", size=22, weight=ft.FontWeight.BOLD),
            ft.Container(height=10),
            id_input,
            pw_input,
            remember_chk,
            error_msg,
            login_btn
        ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)
    )
    page.update()

if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)