import os
import time
import threading
from datetime import datetime, timedelta
import flet as ft
from db_manager import db_service, make_row_key, safe_int, format_seq_chunk_label
from auth_manager import load_saved_login, save_login_state, authenticate
from update_manager import CURRENT_APP_VERSION, check_for_updates, open_download_link

ICONS = getattr(ft, "Icons", getattr(ft, "icons", None))

def pad(left=0, top=0, right=0, bottom=0):
    if hasattr(ft, "padding") and hasattr(ft.padding, "only"):
        return ft.padding.only(left=left, top=top, right=right, bottom=bottom)
    return ft.Padding(left, top, right, bottom)

def main(page: ft.Page):
    page.title = "Optibook-IMS Mobile"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.spacing = 0
    page.bgcolor = "#F4F6F9"

    current_user = {"info": None}
    active_tab = [0]  # 0: 검수, 1: 목록, 2: 내역, 3: 집계
    selected_row_keys = set()
    is_exporting = [False]
    list_display_limit = [100]

    network_icon = ft.Icon(icon=ICONS.WIFI, color="#A5D6A7", size=20)
    user_label = ft.Text("", size=12, color="#FFFFFF", weight=ft.FontWeight.BOLD)

    # ==========================================
    # 공통 다이얼로그 / 스낵바 호환 헬퍼
    # ==========================================
    def show_snack(msg: str, bg_color: str = "#2E7D32"):
        snack = ft.SnackBar(
            content=ft.Text(msg, color="#FFFFFF", weight=ft.FontWeight.BOLD),
            bgcolor=bg_color,
            duration=2500
        )
        try:
            if hasattr(page, "open"):
                page.open(snack)
                return
        except Exception:
            pass
        page.snack_bar = snack
        snack.open = True
        page.update()

    def open_modal(dlg: ft.AlertDialog):
        try:
            if hasattr(page, "open"):
                page.open(dlg)
                return
        except Exception:
            pass
        page.dialog = dlg
        dlg.open = True
        page.update()

    def close_modal(dlg: ft.AlertDialog):
        try:
            if hasattr(page, "close"):
                page.close(dlg)
                return
        except Exception:
            pass
        dlg.open = False
        page.update()

    def update_network_badge(is_online: bool):
        pending_cnt = db_service.get_pending_sync_count()
        if is_online and pending_cnt == 0:
            network_icon.icon = ICONS.WIFI
            network_icon.color = "#A5D6A7"
        elif is_online and pending_cnt > 0:
            network_icon.icon = ICONS.CLOUD_UPLOAD
            network_icon.color = "#FFF59D"
        else:
            network_icon.icon = ICONS.WIFI_OFF
            network_icon.color = "#EF9A9A"

    # ==========================================
    # GitHub 최신 버전 자동 체크
    # ==========================================
    def run_version_check():
        has_update, latest_ver, down_url = check_for_updates()
        if has_update and down_url:
            def start_update(e):
                close_modal(update_dialog)
                open_download_link(down_url, page)

            update_dialog = ft.AlertDialog(
                title=ft.Row([
                    ft.Icon(icon=ICONS.SYSTEM_UPDATE, color="#1565C0"),
                    ft.Text("새 버전 업데이트 알림", size=16, weight=ft.FontWeight.BOLD)
                ]),
                content=ft.Column([
                    ft.Text(f"최신 버전({latest_ver})이 출시되었습니다.", weight=ft.FontWeight.BOLD),
                    ft.Text(f"현재 설치 버전: {CURRENT_APP_VERSION}", size=12, color="#757575"),
                    ft.Text("아래 버튼을 누르면 최신 APK 다운로드 페이지로 연결됩니다.", size=12, color="#444444")
                ], spacing=6, tight=True),
                actions=[
                    ft.Container(
                        content=ft.Text("지금 다운로드", color="#FFFFFF", size=13, weight=ft.FontWeight.BOLD),
                        bgcolor="#1565C0",
                        padding=pad(12, 8, 12, 8),
                        border_radius=6,
                        ink=True,
                        on_click=start_update
                    ),
                    ft.Container(
                        content=ft.Text("나중에", color="#555555", size=13),
                        padding=pad(10, 8, 10, 8),
                        ink=True,
                        on_click=lambda e: close_modal(update_dialog)
                    )
                ]
            )
            open_modal(update_dialog)

    # ==========================================
    # 공통: 엑셀 내보내기 처리
    # ==========================================
    def execute_excel_export(target_books: list, vendor_label: str, trigger_btn_text: ft.Text = None):
        if is_exporting[0]:
            return
        is_exporting[0] = True

        if trigger_btn_text:
            trigger_btn_text.value = "저장 중..."
            page.update()

        try:
            if not target_books:
                alert_empty = ft.AlertDialog(
                    title=ft.Text("알림", weight=ft.FontWeight.BOLD),
                    content=ft.Text("내보낼 도서 데이터가 없습니다."),
                    actions=[
                        ft.Container(
                            content=ft.Text("확인", color="#1565C0", weight=ft.FontWeight.BOLD),
                            padding=pad(12, 6, 12, 6),
                            ink=True,
                            on_click=lambda e: close_modal(alert_empty)
                        )
                    ]
                )
                open_modal(alert_empty)
                return

            file_path = db_service.export_books_to_excel(target_books, vendor_label)
            file_name = os.path.basename(file_path)
            intake_count = len([b for b in target_books if b.get('상태') == '입고'])
            rate_val = round(intake_count / len(target_books) * 100.0, 1) if target_books else 0.0

            if trigger_btn_text:
                trigger_btn_text.value = "✅ 저장 완료!"
                page.update()

            def copy_path_action(e):
                try:
                    page.set_clipboard(file_path)
                    show_snack("파일 저장 경로가 클립보드에 복사되었습니다.")
                except Exception:
                    pass
                close_modal(alert_success)

            alert_success = ft.AlertDialog(
                title=ft.Text("✅ 엑셀 저장 완료", weight=ft.FontWeight.BOLD, color="#2E7D32"),
                content=ft.Column([
                    ft.Text(f"대상: [{vendor_label}]", weight=ft.FontWeight.BOLD, color="#1565C0"),
                    ft.Text(f"총 {len(target_books):,}권 | 입고: {intake_count:,}권 ({rate_val}%)", size=13),
                    ft.Text(f"파일명: {file_name}", size=12, color="#333333", weight=ft.FontWeight.BOLD),
                    ft.Text(f"저장 위치:\n{file_path}", size=11, color="#666666"),
                    ft.Text("※ 스마트폰 [내 파일] -> [Download] 폴더에서 확인하세요.", size=11, color="#1565C0")
                ], spacing=6, tight=True),
                actions=[
                    ft.Container(
                        content=ft.Text("경로 복사", color="#FFFFFF", size=13, weight=ft.FontWeight.BOLD),
                        bgcolor="#1565C0",
                        padding=pad(12, 8, 12, 8),
                        border_radius=6,
                        ink=True,
                        on_click=copy_path_action
                    ),
                    ft.Container(
                        content=ft.Text("닫기", color="#555555", size=13),
                        padding=pad(10, 8, 10, 8),
                        ink=True,
                        on_click=lambda e: close_modal(alert_success)
                    )
                ]
            )
            open_modal(alert_success)
            show_snack(f"엑셀 추출 완료: {file_name}")

        except Exception as ex:
            show_snack(f"엑셀 저장 중 오류 발생: {ex}", "#C62828")
        finally:
            def reset_btn():
                time.sleep(1.5)
                is_exporting[0] = False
                if trigger_btn_text:
                    trigger_btn_text.value = "엑셀 추출"
                    try:
                        page.update()
                    except Exception:
                        pass
            threading.Thread(target=reset_btn, daemon=True).start()

    # ==========================================
    # 탭 1: 현장 검수 화면 (납품처 + 1,000권 구간 필터 + 입고 취소)
    # ==========================================
    inspect_vendor_filter = ft.Dropdown(label="작업 납품처", expand=True, value="전체")
    inspect_range_filter = ft.Dropdown(label="순번 구간(1000권)", width=145, value="전체 구간")
    inspect_progress_text = ft.Text("진행률: 0 / 0권 (0.0%)", size=12, weight=ft.FontWeight.BOLD, color="#1565C0")
    inspect_progress_bar = ft.ProgressBar(value=0, color="#2E7D32", bgcolor="#E0E0E0", height=8)

    scan_result_title = ft.Text("바코드 또는 ISBN 끝 4자리를 입력하세요", size=16, weight=ft.FontWeight.BOLD, color="#222222")
    scan_result_info = ft.Text("1,000권 단위 구간을 선택해 박스별 입고율을 확인할 수 있습니다.", size=12, color="#555555")
    scan_badge_text = ft.Text("대기 중", color="#FFFFFF", size=12, weight=ft.FontWeight.BOLD)
    scan_badge = ft.Container(
        content=scan_badge_text,
        bgcolor="#757575",
        padding=pad(10, 4, 10, 4),
        border_radius=6
    )
    scan_card_container = ft.Container(
        content=ft.Column([
            scan_result_title,
            scan_result_info,
            ft.Row([scan_badge], alignment=ft.MainAxisAlignment.END)
        ], spacing=6),
        padding=12,
        bgcolor="#FFFFFF",
        border_radius=10,
        border=ft.border.all(1.5, "#E0E0E0")
    )

    recent_list_view = ft.ListView(expand=True, spacing=6)

    def refresh_inspect_range_options():
        v = inspect_vendor_filter.value or "전체"
        r_opts = db_service.get_range_options(v)
        inspect_range_filter.options = [ft.dropdown.Option(o) for o in r_opts]
        if inspect_range_filter.value not in r_opts:
            inspect_range_filter.value = "전체 구간"

    def refresh_inspect_progress():
        v = inspect_vendor_filter.value or "전체"
        r = inspect_range_filter.value or "전체 구간"
        prog = db_service.get_vendor_progress(v, r)
        range_tag = f" · [{r}구간]" if r != "전체 구간" else ""
        inspect_progress_text.value = (
            f"[{v}{range_tag}] 입고 {prog['intake']:,} / {prog['total']:,}권 "
            f"({prog['rate_float']}%) · 미입고 {prog['pending']:,}권"
        )
        inspect_progress_bar.value = prog['rate'] / 100.0

    def handle_undo_scan(row_key: str):
        ok, updated_row, is_online = db_service.toggle_book_intake_by_key(row_key)
        update_network_badge(is_online)
        if ok and updated_row:
            scan_result_title.value = f"[입고 취소됨] {updated_row.get('도서명', '')}"
            scan_result_info.value = f"순번 #{updated_row.get('순번', '')} | 상태가 '미입고'로 되돌려졌습니다."
            scan_badge.bgcolor = "#616161"
            scan_badge_text.value = "입고 취소 완료"
            scan_card_container.border = ft.border.all(1.5, "#757575")
            refresh_inspect_progress()
            update_recent_list()
            show_snack(f"입고 취소 완료: {updated_row.get('도서명', '')[:15]}", "#616161")
            page.update()

    def update_recent_list():
        recent_list_view.controls.clear()
        for book in db_service.recent_scans[:20]:
            r_key = make_row_key(book)
            eff_s = safe_int(book.get('_eff_seq', book.get('순번', 1)), 1)
            chunk_lbl = book.get('_chunk_label') or format_seq_chunk_label(eff_s)
            recent_list_view.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(
                                f"#{book.get('순번', eff_s)} {book.get('도서명', '')}",
                                size=13, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS
                            ),
                            ft.Text(
                                f"[{book.get('납품처', '')} · {chunk_lbl}구간] {book.get('ISBN_Clean', '')} | {book.get('입고일시', '')[11:]}",
                                size=11, color="#666666"
                            )
                        ], expand=True, spacing=2),
                        ft.Container(
                            content=ft.Text("입고취소", color="#C62828", size=11, weight=ft.FontWeight.BOLD),
                            bgcolor="#FFEBEE",
                            padding=pad(8, 5, 8, 5),
                            border_radius=6,
                            ink=True,
                            on_click=lambda e, k=r_key: handle_undo_scan(k)
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=10,
                    bgcolor="#FFFFFF",
                    border_radius=8,
                    border=ft.border.all(1, "#EEEEEE")
                )
            )

    def execute_barcode_scan(raw_value: str):
        isbn = str(raw_value).strip()
        barcode_field.value = ""
        if not isbn:
            try:
                barcode_field.focus()
            except Exception:
                pass
            page.update()
            return

        target_vendor = inspect_vendor_filter.value or "전체"
        target_range = inspect_range_filter.value or "전체 구간"
        status, book, is_online = db_service.process_barcode_scan(isbn, target_vendor, target_range)
        update_network_badge(is_online)

        if status == "SUCCESS":
            rem = book.get('_remaining_copies', 0)
            rem_msg = f" (미입고 복본 {rem}권 남음)" if rem > 0 else ""
            c_lbl = book.get('_chunk_label', '')
            scan_result_title.value = book.get('도서명', '')
            scan_result_info.value = (
                f"[{book.get('납품처', '')}] #{book.get('순번', '')} ({c_lbl}구간) | "
                f"정가: {safe_int(book.get('정가', 0)):,}원{rem_msg}"
            )
            scan_badge.bgcolor = "#2E7D32"
            scan_badge_text.value = f"✅ 입고 완료 ({c_lbl})"
            scan_card_container.border = ft.border.all(2, "#2E7D32")
            refresh_inspect_progress()
            update_recent_list()
        elif status == "ALREADY_IN":
            c_lbl = book.get('_chunk_label', '')
            scan_result_title.value = book.get('도서명', '')
            scan_result_info.value = f"[{book.get('납품처', '')} · {c_lbl}구간] 해당 도서는 이미 입고 완료되었습니다."
            scan_badge.bgcolor = "#F57C00"
            scan_badge_text.value = "⚠️ 기입고 도서"
            scan_card_container.border = ft.border.all(2, "#F57C00")
        elif status == "WRONG_RANGE":
            scan_result_title.value = f"🚨 다른 순번 구간 도서입니다! (#{book.get('seq', '')})"
            scan_result_info.value = f"현재 설정 구간: [{target_range}] ≠ 실제 도서 구간: [{book.get('target_range', '')}]"
            scan_badge.bgcolor = "#1565C0"
            scan_badge_text.value = f"구간 불일치 ({book.get('target_range', '')})"
            scan_card_container.border = ft.border.all(2, "#1565C0")
        elif status == "WRONG_VENDOR":
            scan_result_title.value = "🚨 다른 납품처 도서입니다!"
            scan_result_info.value = f"현재 고정: [{target_vendor}] ≠ 실제 소속: [{book.get('target', '')}]"
            scan_badge.bgcolor = "#D32F2F"
            scan_badge_text.value = "납품처 불일치"
            scan_card_container.border = ft.border.all(2, "#D32F2F")
        elif status == "MULTIPLE_SUFFIX":
            scan_result_title.value = f"끝자리 [{book.get('query', '')}] 중복 ({book.get('count', 0)}종)"
            scan_result_info.value = "동일한 끝자리 도서가 여러 권 있습니다. 전체 바코드를 스캔해 주세요."
            scan_badge.bgcolor = "#1565C0"
            scan_badge_text.value = "전체 바코드 필요"
            scan_card_container.border = ft.border.all(2, "#1565C0")
        else:
            scan_result_title.value = "❌ 미등록 도서 (바코드 불일치)"
            scan_result_info.value = f"입력된 번호: {isbn}"
            scan_badge.bgcolor = "#C62828"
            scan_badge_text.value = "스캔 실패"
            scan_card_container.border = ft.border.all(2, "#C62828")

        try:
            barcode_field.focus()
        except Exception:
            pass
        page.update()

    barcode_field = ft.TextField(
        label="바코드 스캔 또는 ISBN 끝 4자리 입력",
        hint_text="예: 97889... 또는 끝 4자리",
        autofocus=True,
        expand=True,
        keyboard_type=ft.KeyboardType.NUMBER,
        on_submit=lambda e: execute_barcode_scan(e.control.value)
    )

    def on_inspect_vendor_change(e):
        inspect_range_filter.value = "전체 구간"
        refresh_inspect_range_options()
        refresh_inspect_progress()
        page.update()

    def on_inspect_range_change(e):
        refresh_inspect_progress()
        page.update()

    inspect_vendor_filter.on_change = on_inspect_vendor_change
    inspect_range_filter.on_change = on_inspect_range_change

    def build_inspect_view():
        vendors = db_service.get_vendor_list()
        inspect_vendor_filter.options = [ft.dropdown.Option(v) for v in vendors]
        if inspect_vendor_filter.value not in vendors:
            inspect_vendor_filter.value = "전체"
        refresh_inspect_range_options()
        refresh_inspect_progress()

        return ft.Column([
            ft.Row([inspect_vendor_filter, inspect_range_filter], spacing=8),
            ft.Container(
                content=ft.Column([inspect_progress_text, inspect_progress_bar], spacing=4),
                padding=pad(4, 0, 4, 2)
            ),
            ft.Row([
                barcode_field,
                ft.Container(
                    content=ft.Text("입고확인", color="#FFFFFF", size=13, weight=ft.FontWeight.BOLD),
                    bgcolor="#1565C0",
                    padding=pad(14, 15, 14, 15),
                    border_radius=8,
                    ink=True,
                    on_click=lambda e: execute_barcode_scan(barcode_field.value)
                )
            ], spacing=8),
            scan_card_container,
            ft.Row([
                ft.Text("최근 스캔 내역 (오류 시 [입고취소] 터치)", size=13, weight=ft.FontWeight.BOLD, color="#1565C0"),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            recent_list_view
        ], expand=True, spacing=8)

    # ==========================================
    # 탭 2: 도서 목록 화면 (1,000권 구간 필터 + 구간 입고율 배지)
    # ==========================================
    list_search_field = ft.TextField(
        label="도서명 / ISBN / 순번 검색",
        expand=True,
        on_submit=lambda e: (list_display_limit.__setitem__(0, 100), render_book_list())
    )
    list_vendor_dropdown = ft.Dropdown(label="납품처", expand=True, value="전체")
    list_range_dropdown = ft.Dropdown(label="순번 구간(1000권)", width=135, value="전체 구간")
    list_status_dropdown = ft.Dropdown(
        label="상태",
        width=95,
        value="전체",
        options=[ft.dropdown.Option("전체"), ft.dropdown.Option("입고"), ft.dropdown.Option("미입고")]
    )
    list_chunk_rate_text = ft.Text("", size=12, weight=ft.FontWeight.BOLD, color="#1565C0")
    list_chunk_rate_bar = ft.ProgressBar(value=0, color="#2E7D32", bgcolor="#BBDEFB", height=6)

    select_all_chk = ft.Checkbox(label="전체 선택 (0건)", value=False)
    btn_export_text = ft.Text("엑셀 추출", color="#FFFFFF", size=12, weight=ft.FontWeight.BOLD)
    book_list_container = ft.ListView(expand=True, spacing=6)
    current_filtered_books = []

    def refresh_list_range_options():
        v = list_vendor_dropdown.value or "전체"
        r_opts = db_service.get_range_options(v)
        list_range_dropdown.options = [ft.dropdown.Option(o) for o in r_opts]
        if list_range_dropdown.value not in r_opts:
            list_range_dropdown.value = "전체 구간"

    def toggle_select_all(e):
        is_checked = bool(select_all_chk.value)
        selected_row_keys.clear()
        if is_checked:
            for b in current_filtered_books:
                selected_row_keys.add(make_row_key(b))
        render_book_list(refresh_data=False)

    select_all_chk.on_change = toggle_select_all

    def handle_list_tab_export(e):
        if selected_row_keys:
            target_books = [b for b in current_filtered_books if make_row_key(b) in selected_row_keys]
        else:
            target_books = current_filtered_books
        v_name = list_vendor_dropdown.value or "전체"
        r_name = list_range_dropdown.value or "전체 구간"
        export_label = f"{v_name}_{r_name}" if r_name != "전체 구간" else v_name
        execute_excel_export(target_books, export_label, btn_export_text)

    btn_export_excel = ft.Container(
        content=ft.Row([
            ft.Icon(icon=ICONS.FILE_DOWNLOAD, color="#FFFFFF", size=16),
            btn_export_text
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=4),
        bgcolor="#2E7D32",
        padding=pad(12, 8, 12, 8),
        border_radius=6,
        ink=True,
        on_click=handle_list_tab_export
    )

    def toggle_book_select(r_key: str, checked: bool):
        if checked:
            selected_row_keys.add(r_key)
        else:
            selected_row_keys.discard(r_key)
        total_cnt = len(current_filtered_books)
        select_all_chk.value = (len(selected_row_keys) == total_cnt and total_cnt > 0)
        select_all_chk.label = f"전체 선택 ({len(selected_row_keys):,}/{total_cnt:,}건)"
        page.update()

    def handle_direct_status_toggle(r_key: str):
        ok, updated_row, is_online = db_service.toggle_book_intake_by_key(r_key)
        update_network_badge(is_online)
        if ok and updated_row:
            new_st = updated_row.get('상태', '')
            show_snack(
                f"[{new_st}] {updated_row.get('도서명', '')[:16]}",
                "#2E7D32" if new_st == "입고" else "#616161"
            )
            render_book_list(refresh_data=True)

    def load_more_books(e):
        list_display_limit[0] += 100
        render_book_list(refresh_data=False)

    def render_book_list(refresh_data=True):
        nonlocal current_filtered_books
        v = list_vendor_dropdown.value or "전체"
        r = list_range_dropdown.value or "전체 구간"
        s = list_status_dropdown.value or "전체"
        q = list_search_field.value or ""

        if refresh_data:
            current_filtered_books = db_service.get_filtered_books(v, s, q, r)

        # 선택된 구간(1~1000, 1001~2000 등)의 입고율 표시 업데이트
        prog = db_service.get_vendor_progress(v, r)
        r_title = f"[{r}번 구간]" if r != "전체 구간" else "[전체 구간]"
        list_chunk_rate_text.value = (
            f"{r_title} 입고율: {prog['rate_float']}% "
            f"(전체 {prog['total']:,}권 · 입고 {prog['intake']:,}권 · 미입고 {prog['pending']:,}권)"
        )
        list_chunk_rate_bar.value = prog['rate'] / 100.0

        total_cnt = len(current_filtered_books)
        select_all_chk.value = (len(selected_row_keys) == total_cnt and total_cnt > 0)
        select_all_chk.label = f"전체 선택 ({len(selected_row_keys):,}/{total_cnt:,}건)"

        book_list_container.controls.clear()

        if not current_filtered_books:
            book_list_container.controls.append(
                ft.Container(
                    content=ft.Text("조건에 맞는 도서가 없습니다.", color="#757575", size=14),
                    alignment=ft.Alignment(0, 0),
                    padding=30
                )
            )
            page.update()
            return

        visible_books = current_filtered_books[:list_display_limit[0]]
        for b in visible_books:
            r_key = make_row_key(b)
            isbn = b.get('ISBN_Clean', '')
            st = b.get('상태', '미입고')
            is_in = (st == "입고")
            st_color = "#2E7D32" if is_in else "#C62828"
            is_checked = r_key in selected_row_keys

            eff_seq = safe_int(b.get('_eff_seq', b.get('순번', 0)), 0)
            raw_seq = str(b.get('순번', '')).strip()
            seq_display = f"#{raw_seq}" if raw_seq and str(eff_seq) == raw_seq else f"#{eff_seq} (원순번:{raw_seq or '-'})"
            chunk_tag = format_seq_chunk_label(eff_seq)

            chk = ft.Checkbox(value=is_checked)
            chk.on_change = lambda e, k=r_key: toggle_book_select(k, bool(e.control.value))

            book_list_container.controls.append(
                ft.Container(
                    content=ft.Row([
                        chk,
                        ft.Column([
                            ft.Row([
                                ft.Text(
                                    f"{seq_display} {b.get('도서명', '')}",
                                    size=13, weight=ft.FontWeight.BOLD, expand=True,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS
                                ),
                                ft.Container(
                                    content=ft.Text(
                                        "입고 완료 (취소)" if is_in else "미입고 (입고처리)",
                                        color="#FFFFFF", size=10, weight=ft.FontWeight.BOLD
                                    ),
                                    bgcolor=st_color,
                                    padding=pad(8, 4, 8, 4),
                                    border_radius=4,
                                    ink=True,
                                    on_click=lambda e, k=r_key: handle_direct_status_toggle(k)
                                )
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Text(
                                f"[{b.get('납품처', '')} · {chunk_tag}구간] {b.get('저자', '')} | {b.get('출판사', '')}",
                                size=11, color="#666666", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS
                            ),
                            ft.Text(
                                f"ISBN: {isbn} | 정가: {safe_int(b.get('정가', 0)):,}원 | {b.get('권수', '1')}권",
                                size=11, color="#333333"
                            )
                        ], expand=True, spacing=3)
                    ], alignment=ft.MainAxisAlignment.START, spacing=4),
                    padding=8,
                    bgcolor="#FFFFFF",
                    border_radius=8,
                    border=ft.border.all(1, "#E8EEF5")
                )
            )

        if total_cnt > list_display_limit[0]:
            rem_cnt = total_cnt - list_display_limit[0]
            book_list_container.controls.append(
                ft.Container(
                    content=ft.Text(
                        f"🔽 도서 더보기 (+100권 / 남은 도서 {rem_cnt:,}권)",
                        color="#1565C0", size=13, weight=ft.FontWeight.BOLD
                    ),
                    alignment=ft.Alignment(0, 0),
                    bgcolor="#E3F2FD",
                    padding=12,
                    border_radius=8,
                    ink=True,
                    on_click=load_more_books
                )
            )

        page.update()

    def on_list_vendor_change(e):
        selected_row_keys.clear()
        list_display_limit[0] = 100
        list_range_dropdown.value = "전체 구간"
        refresh_list_range_options()
        render_book_list()

    list_vendor_dropdown.on_change = on_list_vendor_change
    list_range_dropdown.on_change = lambda e: (
        selected_row_keys.clear(),
        list_display_limit.__setitem__(0, 100),
        render_book_list()
    )
    list_status_dropdown.on_change = lambda e: (
        selected_row_keys.clear(),
        list_display_limit.__setitem__(0, 100),
        render_book_list()
    )

    def build_list_view():
        vendors = db_service.get_vendor_list()
        list_vendor_dropdown.options = [ft.dropdown.Option(v) for v in vendors]
        if list_vendor_dropdown.value not in vendors:
            list_vendor_dropdown.value = "전체"
        refresh_list_range_options()

        return ft.Column([
            ft.Row([list_vendor_dropdown, list_range_dropdown, list_status_dropdown], spacing=6),
            ft.Container(
                content=ft.Column([list_chunk_rate_text, list_chunk_rate_bar], spacing=4),
                padding=pad(10, 6, 10, 6),
                bgcolor="#E3F2FD",
                border_radius=8
            ),
            ft.Row([
                list_search_field,
                ft.Container(
                    content=ft.Icon(icon=ICONS.SEARCH, color="#FFFFFF"),
                    bgcolor="#1565C0",
                    padding=12,
                    border_radius=8,
                    ink=True,
                    on_click=lambda e: (list_display_limit.__setitem__(0, 100), render_book_list())
                )
            ], spacing=8),
            ft.Row([
                select_all_chk,
                btn_export_excel
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            book_list_container
        ], expand=True, spacing=6)

    # ==========================================
    # 탭 3: 일자별 입고 내역 화면
    # ==========================================
    history_date_input = ft.TextField(
        value=datetime.now().strftime("%Y-%m-%d"),
        label="입고 일자 (YYYY-MM-DD)",
        expand=True,
        text_align=ft.TextAlign.CENTER
    )
    history_stat_text = ft.Text("입고 건수: 0권 | 총액: 0원", size=13, weight=ft.FontWeight.BOLD, color="#1565C0")
    history_list_container = ft.ListView(expand=True, spacing=6)

    def render_history_list(target_date=None):
        if not target_date:
            target_date = history_date_input.value.strip() or datetime.now().strftime("%Y-%m-%d")
        history_date_input.value = target_date

        books = db_service.get_history_books(target_date)
        history_list_container.controls.clear()

        total_price = sum(safe_int(b.get('정가', 0)) for b in books)
        history_stat_text.value = f"[{target_date}] 입고: {len(books):,}권 | 정가 합계: {total_price:,}원"

        if not books:
            history_list_container.controls.append(
                ft.Container(
                    content=ft.Text(f"[{target_date}] 입고된 도서 내역이 없습니다.", color="#757575", size=14),
                    alignment=ft.Alignment(0, 0),
                    padding=30
                )
            )
        else:
            for idx, b in enumerate(books, start=1):
                intake_time = str(b.get('입고일시', ''))
                history_list_container.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(
                                    f"#{idx} (순번:{b.get('순번', '-')}) {b.get('도서명', '')}",
                                    size=13, weight=ft.FontWeight.BOLD, expand=True,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS
                                ),
                                ft.Container(
                                    content=ft.Text(
                                        f"⏰ {intake_time[11:] if len(intake_time) >= 16 else intake_time}",
                                        color="#1565C0", size=11, weight=ft.FontWeight.BOLD
                                    ),
                                    bgcolor="#E3F2FD",
                                    padding=pad(6, 2, 6, 2),
                                    border_radius=4
                                )
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Text(f"납품처: {b.get('납품처', '')} | 거래처: {b.get('거래처', '')}", size=11, color="#666666"),
                            ft.Row([
                                ft.Text(f"ISBN: {b.get('ISBN_Clean', '')}", size=11, color="#444444"),
                                ft.Text(
                                    f"정가: {safe_int(b.get('정가', 0)):,}원 | {b.get('권수', '1')}권",
                                    size=11, weight=ft.FontWeight.BOLD, color="#2E7D32"
                                )
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                        ], spacing=4),
                        padding=10,
                        bgcolor="#FFFFFF",
                        border_radius=8,
                        border=ft.border.all(1, "#EEEEEE")
                    )
                )
        page.update()

    def build_history_view():
        return ft.Column([
            ft.Row([
                history_date_input,
                ft.Container(
                    content=ft.Text("오늘", color="#FFFFFF", size=12, weight=ft.FontWeight.BOLD),
                    bgcolor="#1565C0",
                    padding=pad(12, 12, 12, 12),
                    border_radius=6,
                    ink=True,
                    on_click=lambda e: render_history_list(datetime.now().strftime("%Y-%m-%d"))
                ),
                ft.Container(
                    content=ft.Text("어제", color="#333333", size=12, weight=ft.FontWeight.BOLD),
                    bgcolor="#E0E0E0",
                    padding=pad(12, 12, 12, 12),
                    border_radius=6,
                    ink=True,
                    on_click=lambda e: render_history_list((datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
                ),
                ft.Container(
                    content=ft.Icon(icon=ICONS.SEARCH, color="#FFFFFF"),
                    bgcolor="#2E7D32",
                    padding=10,
                    border_radius=6,
                    ink=True,
                    on_click=lambda e: render_history_list()
                )
            ], spacing=6),
            ft.Container(
                content=history_stat_text,
                padding=12,
                bgcolor="#E8F5E9",
                border_radius=8
            ),
            history_list_container
        ], expand=True, spacing=8)

    # ==========================================
    # 탭 4: 집계 화면 (1,000권 단위 구간별 입고율 대시보드 + 납품처별 현황)
    # ==========================================
    def navigate_to_filtered_list(vendor="전체", status="전체", seq_range="전체 구간"):
        selected_row_keys.clear()
        select_all_chk.value = False
        list_display_limit[0] = 100
        list_vendor_dropdown.value = vendor
        refresh_list_range_options()
        list_range_dropdown.value = seq_range
        list_status_dropdown.value = status
        list_search_field.value = ""
        switch_tab(1)

    summary_chunk_vendor_dropdown = ft.Dropdown(label="1,000권 구간 조회 대상 납품처", expand=True, value="전체")
    summary_scroll_view = ft.ListView(expand=True, spacing=8)

    def on_summary_chunk_vendor_change(e):
        render_summary_view()

    summary_chunk_vendor_dropdown.on_change = on_summary_chunk_vendor_change

    def focus_vendor_chunks(vendor_name: str):
        summary_chunk_vendor_dropdown.value = vendor_name
        render_summary_view()
        show_snack(f"[{vendor_name}]의 1,000권 단위 구간 입고율을 표시합니다.", "#1565C0")

    def render_summary_view():
        data = db_service.get_summary_data()
        vendors = db_service.get_vendor_list()
        summary_chunk_vendor_dropdown.options = [ft.dropdown.Option(v) for v in vendors]
        if summary_chunk_vendor_dropdown.value not in vendors:
            summary_chunk_vendor_dropdown.value = "전체"

        target_chunk_vendor = summary_chunk_vendor_dropdown.value or "전체"
        chunks = db_service.get_chunk_summary(target_chunk_vendor)
        total_rate = round((data['intake_qty'] / data['total_qty'] * 100.0), 1) if data['total_qty'] > 0 else 0.0

        summary_scroll_view.controls.clear()

        # 1. 전체 납품 총괄 카드
        summary_scroll_view.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Text(f"전체 납품 총괄 ({total_rate}%)", size=15, weight=ft.FontWeight.BOLD, color="#FFFFFF"),
                        ft.Container(
                            content=ft.Row([
                                ft.Icon(icon=ICONS.FILE_DOWNLOAD, color="#FFFFFF", size=14),
                                ft.Text("전체 엑셀", color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD)
                            ], spacing=4),
                            bgcolor="#2E7D32",
                            padding=pad(10, 5, 10, 5),
                            border_radius=6,
                            ink=True,
                            on_click=lambda e: execute_excel_export(db_service.get_filtered_books("전체"), "전체납품처")
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Divider(color="#90CAF9", height=8),
                    ft.Row([
                        ft.Container(
                            content=ft.Text(f"전체 {data['total_qty']:,}권", size=13, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                            ink=True,
                            padding=pad(6, 4, 6, 4),
                            border_radius=4,
                            on_click=lambda e: navigate_to_filtered_list("전체", "전체", "전체 구간")
                        ),
                        ft.Container(
                            content=ft.Text(f"입고 {data['intake_qty']:,}권", size=13, color="#C8E6C9", weight=ft.FontWeight.BOLD),
                            ink=True,
                            padding=pad(6, 4, 6, 4),
                            border_radius=4,
                            on_click=lambda e: navigate_to_filtered_list("전체", "입고", "전체 구간")
                        ),
                        ft.Container(
                            content=ft.Text(f"미입고 {data['pending_qty']:,}권", size=13, color="#FFCDD2", weight=ft.FontWeight.BOLD),
                            ink=True,
                            padding=pad(8, 4, 8, 4),
                            border_radius=4,
                            bgcolor="#B71C1C",
                            on_click=lambda e: navigate_to_filtered_list("전체", "미입고", "전체 구간")
                        ),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(f"총 정가 합계: {data['total_price']:,} 원", size=13, color="#FFFFFF", weight=ft.FontWeight.BOLD)
                ], spacing=6),
                padding=14,
                bgcolor="#1565C0",
                border_radius=10
            )
        )

        # 2. 전체 순번 기준 1,000권 단위 구간별 입고율 섹션
        summary_scroll_view.controls.append(
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(icon=ICONS.VIEW_TIMELINE, color="#1565C0", size=18),
                        ft.Text(
                            f"1,000권 단위 순번 구간별 입고율 ({len(chunks)}개 구간)",
                            size=14, weight=ft.FontWeight.BOLD, color="#1565C0"
                        )
                    ], spacing=6),
                    ft.Row([summary_chunk_vendor_dropdown])
                ], spacing=6),
                padding=pad(4, 6, 4, 2)
            )
        )

        if not chunks:
            summary_scroll_view.controls.append(
                ft.Container(
                    content=ft.Text("표시할 구간 데이터가 없습니다.", size=13, color="#757575"),
                    padding=15,
                    alignment=ft.Alignment(0, 0)
                )
            )
        else:
            for ch in chunks:
                r_key = ch["range_key"]
                r_flt = ch["rate_float"]
                is_done = (ch["pending"] == 0 and ch["total"] > 0)
                bar_color = "#2E7D32" if is_done else ("#1565C0" if r_flt >= 50 else "#F57C00")
                badge_bg = "#2E7D32" if is_done else "#1565C0"

                summary_scroll_view.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Container(
                                    content=ft.Row([
                                        ft.Container(
                                            content=ft.Text(
                                                f"순번 {ch['label']}",
                                                color="#FFFFFF", size=12, weight=ft.FontWeight.BOLD
                                            ),
                                            bgcolor=badge_bg,
                                            padding=pad(8, 3, 8, 3),
                                            border_radius=4
                                        ),
                                        ft.Text(
                                            f"입고율 {r_flt}% {'(완료)' if is_done else ''}",
                                            size=13, weight=ft.FontWeight.BOLD,
                                            color="#2E7D32" if is_done else "#1565C0"
                                        )
                                    ], spacing=8),
                                    expand=True,
                                    ink=True,
                                    on_click=lambda e, v=target_chunk_vendor, rk=r_key: navigate_to_filtered_list(v, "전체", rk)
                                ),
                                ft.Container(
                                    content=ft.Row([
                                        ft.Icon(icon=ICONS.FILE_DOWNLOAD, color="#1565C0", size=13),
                                        ft.Text("구간엑셀", color="#1565C0", size=11, weight=ft.FontWeight.BOLD)
                                    ], spacing=2),
                                    bgcolor="#E3F2FD",
                                    padding=pad(8, 4, 8, 4),
                                    border_radius=4,
                                    ink=True,
                                    on_click=lambda e, v=target_chunk_vendor, rk=r_key: execute_excel_export(
                                        db_service.get_filtered_books(v, "전체", "", rk),
                                        f"{v}_{rk}구간"
                                    )
                                )
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.ProgressBar(value=ch["rate"] / 100.0, color=bar_color, bgcolor="#E0E0E0", height=7),
                            ft.Row([
                                ft.Container(
                                    content=ft.Text(f"구간전체: {ch['total']:,}권", size=11, color="#555555"),
                                    ink=True,
                                    padding=pad(4, 2, 4, 2),
                                    border_radius=4,
                                    on_click=lambda e, v=target_chunk_vendor, rk=r_key: navigate_to_filtered_list(v, "전체", rk)
                                ),
                                ft.Container(
                                    content=ft.Text(f"입고: {ch['intake']:,}권", size=11, color="#2E7D32", weight=ft.FontWeight.BOLD),
                                    ink=True,
                                    padding=pad(6, 2, 6, 2),
                                    bgcolor="#E8F5E9",
                                    border_radius=4,
                                    on_click=lambda e, v=target_chunk_vendor, rk=r_key: navigate_to_filtered_list(v, "입고", rk)
                                ),
                                ft.Container(
                                    content=ft.Text(f"미입고: {ch['pending']:,}권", size=11, color="#C62828", weight=ft.FontWeight.BOLD),
                                    ink=True,
                                    padding=pad(6, 2, 6, 2),
                                    bgcolor="#FFEBEE",
                                    border_radius=4,
                                    on_click=lambda e, v=target_chunk_vendor, rk=r_key: navigate_to_filtered_list(v, "미입고", rk)
                                ),
                                ft.Text(f"{ch['price']:,}원", size=11, color="#333333", weight=ft.FontWeight.BOLD)
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                        ], spacing=6),
                        padding=11,
                        bgcolor="#FFFFFF",
                        border_radius=8,
                        border=ft.border.all(1.5, "#BBDEFB" if not is_done else "#A5D6A7")
                    )
                )

        # 3. 납품처별 상세 집계 섹션
        summary_scroll_view.controls.append(
            ft.Container(
                content=ft.Text("납품처별 전체 현황", size=14, weight=ft.FontWeight.BOLD, color="#1565C0"),
                padding=pad(4, 10, 4, 2)
            )
        )

        for v in data["vendors"]:
            v_name = v["delivery"]
            rate_flt = round((v["intake"] / v["total"] * 100.0), 1) if v["total"] > 0 else 0.0

            summary_scroll_view.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(icon=ICONS.FOLDER_OPEN, size=16, color="#1565C0"),
                                    ft.Text(
                                        f"[{v['client']}] {v_name} ({rate_flt}%)",
                                        size=13, weight=ft.FontWeight.BOLD,
                                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS
                                    ),
                                ], spacing=4),
                                expand=True,
                                ink=True,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "전체", "전체 구간")
                            ),
                            ft.Row([
                                ft.Container(
                                    content=ft.Text("구간보기", color="#1565C0", size=11, weight=ft.FontWeight.BOLD),
                                    bgcolor="#E3F2FD",
                                    padding=pad(7, 4, 7, 4),
                                    border_radius=4,
                                    ink=True,
                                    on_click=lambda e, name=v_name: focus_vendor_chunks(name)
                                ),
                                ft.Container(
                                    content=ft.Row([
                                        ft.Icon(icon=ICONS.DESCRIPTION, color="#FFFFFF", size=12),
                                        ft.Text("검수서류", color="#FFFFFF", size=11, weight=ft.FontWeight.BOLD)
                                    ], spacing=3),
                                    bgcolor="#1565C0",
                                    padding=pad(8, 4, 8, 4),
                                    border_radius=4,
                                    ink=True,
                                    on_click=lambda e, name=v_name: execute_excel_export(db_service.get_filtered_books(name), name)
                                )
                            ], spacing=4)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.ProgressBar(value=rate_flt / 100.0, color="#2E7D32", bgcolor="#E0E0E0", height=6),
                        ft.Row([
                            ft.Container(
                                content=ft.Text(f"전체: {v['total']:,}권", size=11, color="#555555"),
                                ink=True,
                                padding=pad(4, 2, 4, 2),
                                border_radius=4,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "전체", "전체 구간")
                            ),
                            ft.Container(
                                content=ft.Text(f"입고: {v['intake']:,}권", size=11, color="#2E7D32", weight=ft.FontWeight.BOLD),
                                ink=True,
                                padding=pad(6, 2, 6, 2),
                                bgcolor="#E8F5E9",
                                border_radius=4,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "입고", "전체 구간")
                            ),
                            ft.Container(
                                content=ft.Text(f"미입고: {v['pending']:,}권", size=11, color="#C62828", weight=ft.FontWeight.BOLD),
                                ink=True,
                                padding=pad(6, 2, 6, 2),
                                bgcolor="#FFEBEE",
                                border_radius=4,
                                on_click=lambda e, name=v_name: navigate_to_filtered_list(name, "미입고", "전체 구간")
                            ),
                            ft.Text(f"{v['price']:,}원", size=11, color="#333333", weight=ft.FontWeight.BOLD)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ], spacing=6),
                    padding=12,
                    bgcolor="#FFFFFF",
                    border_radius=8,
                    border=ft.border.all(1, "#E8EEF5")
                )
            )
        page.update()

    def build_summary_view():
        return ft.Column([
            summary_scroll_view
        ], expand=True, spacing=0)

    # ==========================================
    # 스마트폰 하단 시스템 바 겹침 원천 차단 네비게이션 바
    # ==========================================
    content_area = ft.Container(expand=True, padding=pad(12, 8, 12, 4))

    def make_nav_item(idx, icon_name, label_text):
        is_active = (active_tab[0] == idx)
        active_color = "#1565C0" if is_active else "#757575"
        bg_pill = "#E3F2FD" if is_active else "transparent"
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon=icon_name, size=22, color=active_color),
                        bgcolor=bg_pill,
                        padding=pad(14, 3, 14, 3),
                        border_radius=14
                    ),
                    ft.Text(
                        label_text,
                        size=11,
                        weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
                        color=active_color
                    )
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2
            ),
            alignment=ft.Alignment(0, 0),
            expand=True,
            ink=True,
            on_click=lambda e: switch_tab(idx)
        )

    bottom_nav_bar = ft.Container(
        content=ft.Row([], alignment=ft.MainAxisAlignment.SPACE_AROUND),
        bgcolor="#FFFFFF",
        height=78,
        padding=pad(4, 6, 4, 18),
        border=ft.border.only(top=ft.BorderSide(1, "#E0E0E0"))
    )

    def update_bottom_bar():
        bottom_nav_bar.content = ft.Row([
            make_nav_item(0, ICONS.QR_CODE_SCANNER, "검수"),
            make_nav_item(1, ICONS.LIST_ALT, "목록"),
            make_nav_item(2, ICONS.HISTORY, "내역"),
            make_nav_item(3, ICONS.ANALYTICS, "집계"),
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
        update_network_badge(is_online)
        show_snack(
            "서버 DB 동기화 완료" if is_online else "오프라인 상태 (로컬 캐시 데이터 사용 중)",
            "#2E7D32" if is_online else "#F57C00"
        )
        switch_tab(active_tab[0])

    def show_main_screen():
        page.controls.clear()
        u = current_user["info"]
        user_label.value = f"{u.get('user_name', '')} [{u.get('company_id', '')}]"

        page.appbar = ft.AppBar(
            title=ft.Text(f"Optibook-IMS ({CURRENT_APP_VERSION})", size=16, weight=ft.FontWeight.BOLD),
            bgcolor="#1565C0",
            color="#FFFFFF",
            actions=[
                ft.Row([
                    user_label,
                    network_icon,
                    ft.IconButton(
                        icon=ICONS.REFRESH,
                        icon_color="#FFFFFF",
                        tooltip="서버 동기화",
                        on_click=manual_sync
                    )
                ], spacing=4)
            ]
        )

        page.add(
            ft.SafeArea(
                top=True,
                bottom=True,
                minimum_padding=pad(0, 0, 0, 8),
                content=ft.Column([
                    content_area,
                    bottom_nav_bar
                ], expand=True, spacing=0),
                expand=True
            )
        )
        switch_tab(0)

        threading.Thread(target=run_version_check, daemon=True).start()

    # ==========================================
    # 로그인 화면
    # ==========================================
    saved_id, saved_pw = load_saved_login()
    id_input = ft.TextField(label="아이디", value=saved_id, width=310)
    pw_input = ft.TextField(
        label="비밀번호", value=saved_pw, password=True,
        can_reveal_password=True, width=310,
        on_submit=lambda e: handle_login(e)
    )
    remember_chk = ft.Checkbox(label="로그인 정보 저장", value=bool(saved_id))
    error_msg = ft.Text("", color="#C62828", size=13, weight=ft.FontWeight.BOLD)
    login_btn_text = ft.Text("로그인", color="#FFFFFF", size=16, weight=ft.FontWeight.BOLD)

    def handle_login(e):
        uid = id_input.value.strip()
        pw = pw_input.value.strip()
        if not uid or not pw:
            error_msg.value = "아이디와 비밀번호를 모두 입력하세요."
            page.update()
            return

        login_btn_text.value = "접속 및 데이터 동기화 중..."
        error_msg.value = ""
        page.update()

        success, user_info, is_online = authenticate(uid, pw)
        if success:
            save_login_state(uid, pw, bool(remember_chk.value))
            current_user["info"] = user_info
            db_ready = db_service.load_database(user_info.get("company_id", "ALL"))
            update_network_badge(db_ready)
            show_main_screen()
        else:
            login_btn_text.value = "로그인"
            error_msg.value = "계정 정보가 올바르지 않거나 미승인 계정입니다."
            page.update()

    login_btn = ft.Container(
        content=login_btn_text,
        alignment=ft.Alignment(0, 0),
        width=310,
        height=48,
        bgcolor="#1565C0",
        border_radius=8,
        ink=True,
        on_click=handle_login
    )

    page.appbar = ft.AppBar(
        title=ft.Text("Optibook-IMS 로그인", size=17, weight=ft.FontWeight.BOLD),
        bgcolor="#1565C0",
        color="#FFFFFF",
        center_title=True
    )
    page.add(
        ft.SafeArea(
            content=ft.Container(
                content=ft.Column([
                    ft.Container(height=15),
                    ft.Icon(icon=ICONS.MENU_BOOK, size=60, color="#1565C0"),
                    ft.Text("Optibook-IMS Mobile", size=22, weight=ft.FontWeight.BOLD, color="#1565C0"),
                    ft.Text(f"Version {CURRENT_APP_VERSION}", size=12, color="#757575"),
                    ft.Container(height=8),
                    id_input,
                    pw_input,
                    ft.Row([remember_chk], alignment=ft.MainAxisAlignment.CENTER),
                    error_msg,
                    login_btn
                ], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
                alignment=ft.Alignment(0, 0),
                expand=True
            ),
            expand=True
        )
    )
    page.update()

if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)