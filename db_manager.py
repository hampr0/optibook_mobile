import os
import pymysql
import pandas as pd
from datetime import datetime
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from config import DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME, BASE_DIR

DB_FILE = os.path.join(BASE_DIR, "bookst_db.csv")

def get_tidb_connection():
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            charset="utf8mb4",
            ssl={},
            connect_timeout=4,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor
        )
        return conn
    except Exception:
        return None

def sanitize_df(df_in: pd.DataFrame) -> pd.DataFrame:
    if df_in.empty:
        return df_in
    req_cols = ['등록일자', '등록일시', '거래처', '납품처', '내용', '순번', '도서명', '저자', '출판사', '정가', '권수', 'ISBN', 'ISBN_Clean', '상태', '입고일시', '비고', 'company_id']
    for col in req_cols:
        if col not in df_in.columns:
            df_in[col] = ""
    df_in.fillna("", inplace=True)
    df_in = df_in.astype(str)
    mask = (df_in['도서명'] != '') & (df_in['상태'] != '삭제')
    return df_in[mask].reset_index(drop=True)

class DataManager:
    def __init__(self):
        self.df = pd.DataFrame()
        self.is_online = False
        self.recent_scans = []

    def load_database(self, company_id="ALL"):
        conn = get_tidb_connection()
        if conn:
            try:
                self.is_online = True
                cursor = conn.cursor()
                if company_id == 'ALL':
                    query = """SELECT reg_date AS 등록일자, reg_dt AS 등록일시, client AS 거래처, 
                                      delivery AS 납품처, content AS 내용, seq AS 순번, title AS 도서명, 
                                      author AS 저자, publisher AS 출판사, price AS 정가, qty AS 권수, 
                                      isbn AS ISBN, isbn_clean AS ISBN_Clean, status AS 상태, 
                                      intake_dt AS 입고일시, remarks AS 비고, company_id FROM books"""
                    cursor.execute(query)
                else:
                    query = """SELECT reg_date AS 등록일자, reg_dt AS 등록일시, client AS 거래처, 
                                      delivery AS 납품처, content AS 내용, seq AS 순번, title AS 도서명, 
                                      author AS 저자, publisher AS 출판사, price AS 정가, qty AS 권수, 
                                      isbn AS ISBN, isbn_clean AS ISBN_Clean, status AS 상태, 
                                      intake_dt AS 입고일시, remarks AS 비고, company_id FROM books WHERE company_id=%s"""
                    cursor.execute(query, (company_id,))
                
                rows = cursor.fetchall()
                conn.close()
                self.df = sanitize_df(pd.DataFrame(rows))
                self.df.to_csv(DB_FILE, index=False, encoding='utf-8-sig')
                return True
            except Exception:
                pass

        self.is_online = False
        if os.path.exists(DB_FILE):
            try:
                local_df = pd.read_csv(DB_FILE, dtype=str, encoding='utf-8-sig')
                self.df = sanitize_df(local_df)
            except Exception:
                self.df = pd.DataFrame()
        return False

    def process_barcode_scan(self, isbn_input: str, target_vendor: str = "전체"):
        isbn_clean = ''.join(filter(str.isdigit, isbn_input))
        if not isbn_clean or self.df.empty:
            return "NOT_FOUND", None, False

        search_pool = self.df
        if target_vendor != "전체":
            search_pool = self.df[self.df['납품처'] == target_vendor]

        matches = search_pool[search_pool['ISBN_Clean'] == isbn_clean]
        if matches.empty:
            other_matches = self.df[self.df['ISBN_Clean'] == isbn_clean]
            if not other_matches.empty:
                other_vendor = other_matches.iloc[0].get('납품처', '')
                return "WRONG_VENDOR", {"target": other_vendor}, self.is_online
            return "NOT_FOUND", None, self.is_online

        target_idx = matches.index[0]
        row_data = self.df.loc[target_idx].to_dict()

        if row_data.get('상태') == '입고':
            return "ALREADY_IN", row_data, self.is_online

        now_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.df.at[target_idx, '상태'] = '입고'
        self.df.at[target_idx, '입고일시'] = now_dt
        row_data['상태'] = '입고'
        row_data['입고일시'] = now_dt

        try:
            self.df.to_csv(DB_FILE, index=False, encoding='utf-8-sig')
        except Exception:
            pass

        conn = get_tidb_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    c = str(row_data.get('거래처', '')).strip()
                    d = str(row_data.get('납품처', '')).strip()
                    rdt = str(row_data.get('등록일시', '')).strip()
                    cur.execute(
                        "UPDATE books SET status='입고', intake_dt=%s WHERE client=%s AND delivery=%s AND reg_dt=%s AND isbn_clean=%s",
                        (now_dt, c, d, rdt, isbn_clean)
                    )
                conn.close()
                self.is_online = True
            except Exception:
                self.is_online = False

        self.recent_scans.insert(0, row_data)
        if len(self.recent_scans) > 30:
            self.recent_scans.pop()

        return "SUCCESS", row_data, self.is_online

    def get_summary_data(self):
        if self.df.empty:
            return {"total_qty": 0, "intake_qty": 0, "pending_qty": 0, "total_price": 0, "vendors": []}

        t_all = len(self.df)
        d_all = len(self.df[self.df['상태'] == '입고'])
        p_all = t_all - d_all
        try:
            price_all = int(self.df['정가'].astype(float).sum())
        except Exception:
            price_all = 0

        unique_batches = self.df[['거래처', '납품처']].drop_duplicates().reset_index(drop=True)
        vendors = []
        for _, row in unique_batches.iterrows():
            c, v = str(row['거래처']), str(row['납품처'])
            mask = (self.df['거래처'] == c) & (self.df['납품처'] == v)
            v_df = self.df[mask]
            v_t = len(v_df)
            v_d = len(v_df[v_df['상태'] == '입고'])
            v_p = v_t - v_d
            try:
                v_pr = int(v_df['정가'].astype(float).sum())
            except Exception:
                v_pr = 0

            vendors.append({
                "client": c,
                "delivery": v,
                "total": v_t,
                "intake": v_d,
                "pending": v_p,
                "price": v_pr
            })

        return {
            "total_qty": t_all,
            "intake_qty": d_all,
            "pending_qty": p_all,
            "total_price": price_all,
            "vendors": vendors
        }

    def get_filtered_books(self, vendor="전체", status="전체", search_query=""):
        if self.df.empty:
            return []
        f_df = self.df.copy()
        if vendor != "전체":
            f_df = f_df[f_df['납품처'] == vendor]
        if status != "전체":
            f_df = f_df[f_df['상태'] == status]
        if search_query:
            q = search_query.strip().lower()
            mask = f_df['도서명'].astype(str).str.lower().str.contains(q) | f_df['ISBN_Clean'].astype(str).str.contains(q)
            f_df = f_df[mask]
        return f_df.to_dict('records')

    def get_history_books(self, target_date: str = ""):
        if self.df.empty:
            return []
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        mask = (self.df['상태'] == '입고') & (self.df['입고일시'].astype(str).str.startswith(target_date))
        h_df = self.df[mask].copy()
        if h_df.empty:
            return []
        h_df.sort_values(by='입고일시', ascending=False, inplace=True)
        return h_df.to_dict('records')

    def get_vendor_list(self):
        if self.df.empty or '납품처' not in self.df.columns:
            return ["전체"]
        vendors = [v for v in self.df['납품처'].dropna().unique() if str(v).strip() and str(v).strip() != '납품처']
        return ["전체"] + sorted(vendors)

    def export_books_to_excel(self, book_list: list, vendor_name: str = "전체") -> str:
        """선택/납품처별 도서 목록을 납품 서류용 엑셀 포맷으로 내보내기"""
        if not book_list:
            return ""

        def sort_key(item):
            try:
                return int(float(item.get('순번', 0)))
            except Exception:
                return 999999

        sorted_books = sorted(book_list, key=sort_key)

        export_data = []
        for idx, row in enumerate(sorted_books, start=1):
            try: seq_val = int(float(row.get('순번', 0)))
            except: seq_val = row.get('순번', '')
            try: price_val = int(float(row.get('정가', 0)))
            except: price_val = row.get('정가', '')
            try: qty_val = int(float(row.get('권수', 1)))
            except: qty_val = row.get('권수', '1')

            # ISBN 숫자 변환 (삼각형 오류 경고 제거)
            isbn_raw = str(row.get('ISBN_Clean', '')).strip()
            try:
                if isbn_raw.isdigit() and len(isbn_raw) <= 15:
                    isbn_val = int(isbn_raw)
                else:
                    isbn_val = isbn_raw
            except Exception:
                isbn_val = isbn_raw

            export_data.append({
                '전번(전체번호)': idx,
                '거래처': row.get('거래처', ''),
                '납품처': row.get('납품처', ''),
                '내용': row.get('내용', ''),
                '순번': seq_val,
                '도서명': row.get('도서명', ''),
                '저자': row.get('저자', ''),
                '출판사': row.get('출판사', ''),
                '정가': price_val,
                '권수': qty_val,
                'ISBN': isbn_val,
                '입고상태': row.get('상태', ''),
                '작업일자': row.get('입고일시', '')
            })

        export_df = pd.DataFrame(export_data)
        time_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"입고검수내역_{vendor_name}_{time_tag}.xlsx"

        android_download_dir = "/storage/emulated/0/Download"
        if os.path.exists(android_download_dir):
            save_path = os.path.join(android_download_dir, export_filename)
        else:
            save_path = os.path.join(BASE_DIR, export_filename)

        with pd.ExcelWriter(save_path, engine='openpyxl') as writer:
            export_df.to_excel(writer, index=False, sheet_name='입고검수내역')
            ws = writer.sheets['입고검수내역']

            # 표준 서류용 고정 열 너비 설정
            col_widths = {
                'A': 6,   # 전번
                'B': 12,  # 거래처
                'C': 14,  # 납품처
                'D': 10,  # 내용
                'E': 6,   # 순번
                'F': 32,  # 도서명
                'G': 18,  # 저자
                'H': 16,  # 출판사
                'I': 11,  # 정가
                'J': 6,   # 권수
                'K': 15,  # ISBN
                'L': 9,   # 입고상태
                'M': 18   # 작업일자
            }
            for col_letter, width in col_widths.items():
                ws.column_dimensions[col_letter].width = width

            thin_border = Border(
                left=Side(style='thin', color='A0A0A0'),
                right=Side(style='thin', color='A0A0A0'),
                top=Side(style='thin', color='A0A0A0'),
                bottom=Side(style='thin', color='A0A0A0')
            )
            header_fill = PatternFill(start_color='E3F2FD', end_color='E3F2FD', fill_type='solid')
            header_font = Font(name='맑은 고딕', size=10, bold=True, color='1565C0')
            body_font = Font(name='맑은 고딕', size=10)

            # 헤더 서식
            ws.row_dimensions[1].height = 25
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center', shrink_to_fit=True)
                cell.border = thin_border

            # 본문 데이터 서식 (셀에 맞춤 적용)
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
                ws.row_dimensions[row[0].row].height = 20
                for col_idx, cell in enumerate(row, start=1):
                    cell.font = body_font
                    cell.border = thin_border
                    col_name = export_df.columns[col_idx - 1]

                    if col_name in ['도서명', '저자', '출판사', '내용']:
                        cell.alignment = Alignment(horizontal='left', vertical='center', shrink_to_fit=True)
                    elif col_name in ['정가', '권수']:
                        cell.alignment = Alignment(horizontal='right', vertical='center')
                        if col_name == '정가' and isinstance(cell.value, (int, float)):
                            cell.number_format = '#,##0'
                    elif col_name == 'ISBN':
                        cell.alignment = Alignment(horizontal='center', vertical='center')
                        if isinstance(cell.value, (int, float)):
                            cell.number_format = '0'
                    elif col_name == '입고상태':
                        cell.alignment = Alignment(horizontal='center', vertical='center')
                        if str(cell.value) == '입고':
                            cell.font = Font(name='맑은 고딕', size=10, bold=True, color='2E7D32')
                        else:
                            cell.font = Font(name='맑은 고딕', size=10, bold=True, color='C62828')
                    else:
                        cell.alignment = Alignment(horizontal='center', vertical='center', shrink_to_fit=True)

        return save_path

db_service = DataManager()