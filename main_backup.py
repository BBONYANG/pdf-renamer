#!/usr/bin/env python3
"""
PDF Rename GUI (main.py)
Requirements: PySide6 (preferred) or PyQt5 fallback.
Run: pip install PySide6
       python main.py
"""
import sys
import os
import re
import shutil
import uuid
from functools import cmp_to_key

# Try PySide6, fallback to PyQt5
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QListWidget, QFileDialog, QTextEdit, QMessageBox,
    QLabel, QSplitter, QInputDialog, QSizePolicy
    )
    from PySide6.QtCore import Qt, QUrl
except Exception:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QListWidget, QFileDialog, QTextEdit, QMessageBox,
    QLabel, QSplitter, QInputDialog, QSizePolicy
    )
    from PyQt5.QtCore import Qt, QUrl

ILLEGAL_CHARS_RE = re.compile(r"[\\/:\*\?\"<>\|]")
MID_DOT_RE = re.compile(r"\u00B7|·")
PART_RE = re.compile(r"part\s*(\d+)", re.IGNORECASE)


def extract_part_number(filename):
    m = PART_RE.search(filename)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


# Helper: robust text reading for various encodings
def try_read_text_lines(path):
    encodings = ['utf-8', 'cp949', 'cp1252', 'euc-kr', 'iso-8859-1']
    for enc in encodings:
        try:
            with open(path, 'r', encoding=enc) as fh:
                return [ln.rstrip('\n') for ln in fh]
        except Exception:
            # try more tolerant read
            try:
                with open(path, 'r', encoding=enc, errors='ignore') as fh:
                    return [ln.rstrip('\n') for ln in fh]
            except Exception:
                continue
    # last resort
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            return [ln.rstrip('\n') for ln in fh]
    except Exception:
        return []


# Helper: Windows long path handling and safe file ops
def safe_path_for_windows(p):
    if os.name != 'nt' or not p:
        return p
    abs_p = os.path.abspath(p)
    if abs_p.startswith('\\\\?\\'):
        return abs_p
    return '\\\\?\\' + abs_p


def safe_exists(p):
    try:
        if os.path.exists(p):
            return True
        if os.name == 'nt':
            return os.path.exists(safe_path_for_windows(p))
    except Exception:
        return False
    return False


def safe_listdir(d):
    try:
        return os.listdir(d)
    except Exception:
        if os.name == 'nt':
            try:
                return os.listdir(safe_path_for_windows(d))
            except Exception:
                return []
        return []


def safe_rename(src, dst):
    try:
        os.rename(src, dst)
        return True
    except Exception:
        if os.name == 'nt':
            try:
                os.rename(safe_path_for_windows(src), safe_path_for_windows(dst))
                return True
            except Exception:
                return False
        return False


def part_compare(a, b):
    na = extract_part_number(a)
    nb = extract_part_number(b)
    if na is not None and nb is not None:
        return na - nb
    if na is not None:
        return -1
    if nb is not None:
        return 1
    # fallback to lexicographic
    return (a > b) - (a < b)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 1:1 Renamer")
        self.resize(900, 600)

        self.pdf_folder = None
        self.pdf_paths = []  # absolute paths
        self.names = []
        self.last_rename_map = None  # list of tuples (old_abs, new_abs)

        self._build_ui()
        self._closing = False

    def _build_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        layout = QVBoxLayout(w)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setSizes([380, 420])
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(8)

        # Left panel: PDFs
        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(4,4,4,4)
        llay.setSpacing(6)
        btn_folder = QPushButton("폴더 선택")
        btn_folder.clicked.connect(self.select_folder)
        # pdf controls: move up/down/top/bottom/position
        pdf_ctrl = QHBoxLayout()
        self.btn_pdf_up = QPushButton("위로")
        self.btn_pdf_up.clicked.connect(self.move_pdf_up)
        self.btn_pdf_down = QPushButton("아래로")
        self.btn_pdf_down.clicked.connect(self.move_pdf_down)
        self.btn_pdf_top = QPushButton("맨위로")
        self.btn_pdf_top.clicked.connect(self.move_pdf_top)
        self.btn_pdf_bottom = QPushButton("맨아래")
        self.btn_pdf_bottom.clicked.connect(self.move_pdf_bottom)
        self.btn_pdf_pos = QPushButton("위치로 이동")
        self.btn_pdf_pos.clicked.connect(self.move_pdf_to_position)
        pdf_ctrl.addWidget(self.btn_pdf_up)
        pdf_ctrl.addWidget(self.btn_pdf_down)
        pdf_ctrl.addWidget(self.btn_pdf_top)
        pdf_ctrl.addWidget(self.btn_pdf_bottom)
        pdf_ctrl.addWidget(self.btn_pdf_pos)

        self.pdf_list = QListWidget()
        self.pdf_list.setSelectionMode(QListWidget.ExtendedSelection)
        # allow internal drag/drop reorder
        try:
            from PySide6.QtWidgets import QAbstractItemView
        except Exception:
            from PyQt5.QtWidgets import QAbstractItemView
        self.pdf_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.pdf_list.setMinimumWidth(220)
        self.pdf_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        llay.addWidget(btn_folder)
        llay.addLayout(pdf_ctrl)
        llay.addWidget(QLabel("PDF 파일 목록"))
        llay.addWidget(self.pdf_list)

        # Right panel: names
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(4,4,4,4)
        rlay.setSpacing(6)
        self.btn_names = QPushButton("이름 파일 불러오기")
        self.btn_names.clicked.connect(self.load_names_file)
        name_ctrl = QHBoxLayout()
        self.btn_name_up = QPushButton("위로")
        self.btn_name_up.clicked.connect(self.move_name_up)
        self.btn_name_down = QPushButton("아래로")
        self.btn_name_down.clicked.connect(self.move_name_down)
        self.btn_name_top = QPushButton("맨위로")
        self.btn_name_top.clicked.connect(self.move_name_top)
        self.btn_name_bottom = QPushButton("맨아래")
        self.btn_name_bottom.clicked.connect(self.move_name_bottom)
        self.btn_name_pos = QPushButton("위치로 이동")
        self.btn_name_pos.clicked.connect(self.move_name_to_position)
        self.btn_name_delete = QPushButton("선택 항목 삭제")
        self.btn_name_delete.clicked.connect(self.delete_selected_names)
        name_ctrl.addWidget(self.btn_name_up)
        name_ctrl.addWidget(self.btn_name_down)
        name_ctrl.addWidget(self.btn_name_top)
        name_ctrl.addWidget(self.btn_name_bottom)
        name_ctrl.addWidget(self.btn_name_pos)
        name_ctrl.addWidget(self.btn_name_delete)

        self.name_list = QListWidget()
        # avoid fixed width; allow expanding to align with PDF list
        self.name_list.setMinimumWidth(200)
        self.name_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.name_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.name_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        rlay.addWidget(self.btn_names)
        rlay.addLayout(name_ctrl)
        rlay.addWidget(QLabel("이름 리스트"))
        rlay.addWidget(self.name_list)

        splitter.addWidget(left)
        splitter.addWidget(right)
        # make left/right balanced
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # Preview area
        preview_label = QLabel("매칭 미리보기 (실시간)")
        self.preview = QListWidget()
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(preview_label)
        layout.addWidget(self.preview)

        # Buttons row
        brow = QHBoxLayout()
        self.btn_rename = QPushButton("Rename 실행")
        self.btn_rename.clicked.connect(self.rename_execute)
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_undo.setEnabled(False)
        brow.addWidget(self.btn_rename)
        brow.addWidget(self.btn_undo)
        layout.addLayout(brow)

        # Log
        layout.addWidget(QLabel("로그"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        # Connections for live preview and syncing (use lambdas to ignore signal args)
        self.pdf_list.model().rowsInserted.connect(lambda *a: self.sync_and_update())
        self.pdf_list.model().rowsRemoved.connect(lambda *a: self.sync_and_update())
        self.pdf_list.model().layoutChanged.connect(lambda *a: self.sync_and_update())
        self.pdf_list.model().modelReset.connect(lambda *a: self.sync_and_update())
        try:
            self.pdf_list.model().rowsMoved.connect(lambda *a: self.sync_and_update())
        except Exception:
            pass
        self.name_list.model().rowsInserted.connect(lambda *a: self.sync_and_update())
        self.name_list.model().rowsRemoved.connect(lambda *a: self.sync_and_update())
        self.name_list.model().layoutChanged.connect(lambda *a: self.sync_and_update())
        self.name_list.model().modelReset.connect(lambda *a: self.sync_and_update())
        try:
            self.name_list.model().rowsMoved.connect(lambda *a: self.sync_and_update())
        except Exception:
            pass

        # Drag & drop support
        # Accept drops on the main window so drag/drop events reach the handlers
        self.setAcceptDrops(True)
        self._central_widget = w

    def log_append(self, msg):
        self.log.append(msg)

    # Drag & drop events: accept folders and names.txt
    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        md = event.mimeData()
        urls = md.urls()
        handled = False
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                # load the folder (last folder will be active)
                self.load_folder(path)
                handled = True
                continue
            if os.path.isfile(path):
                ext = os.path.splitext(path)[1].lower()
                if ext in ('.txt', '.csv', '.xlsx'):
                    # append names when multiple files are dropped
                    self.load_names_file(path, append=True)
                    handled = True
                    continue
                # allow dropping single pdf: load its parent folder
                if os.path.basename(path).lower().endswith('.pdf'):
                    self.load_folder(os.path.dirname(path))
                    handled = True
                    continue
        if handled:
            event.acceptProposedAction()
        else:
            event.ignore()

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if folder:
            self.load_folder(folder)

    def load_folder(self, folder):
        self.pdf_folder = folder
        # list pdf files
        files = [f for f in os.listdir(folder) if f.lower().endswith('.pdf')]
        # sort by part number
        files.sort(key=cmp_to_key(part_compare))
        self.pdf_paths = [os.path.join(folder, f) for f in files]
        self.pdf_list.clear()
        for f in files:
            self.pdf_list.addItem(f)
        self.log_append(f"Loaded {len(files)} PDFs from: {folder}")
        self.update_preview()

    def load_names_file(self, path=None, append=False):
        # clicked signal sometimes passes a bool; ignore it
        if isinstance(path, bool):
            path = None
        # Support .txt, .csv, .xlsx (Excel) - read first column for csv/xlsx
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "이름 파일 열기", "", "Text/CSV/Excel Files (*.txt *.csv *.xlsx);;All Files (*)")
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        names = []
        try:
            if ext == '.txt':
                lines = try_read_text_lines(path)
                names = [ln.strip() for ln in lines if ln.strip()]
            elif ext == '.csv':
                import csv, io
                lines = try_read_text_lines(path)
                sio = io.StringIO('\n'.join(lines))
                reader = csv.reader(sio)
                for row in reader:
                    if row:
                        val = row[0].strip()
                        if val:
                            names.append(val)
            elif ext == '.xlsx':
                QMessageBox.information(self, 'XLSX 안내', 'XLSX 파일은 A열만 읽습니다. 복잡한 서식(병합, 수식 등)은 지원되지 않습니다.')
                # Parse .xlsx using zipfile + xml to avoid extra deps. Read first worksheet and column A.
                try:
                    import zipfile
                    import xml.etree.ElementTree as ET
                    with zipfile.ZipFile(path) as zf:
                        namelist = zf.namelist()
                        shared = []
                        if 'xl/sharedStrings.xml' in namelist:
                            ss = zf.read('xl/sharedStrings.xml')
                            root = ET.fromstring(ss)
                            # spreadsheetml namespace
                            ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                            for si in root.findall('.//%ssi' % ns):
                                texts = si.findall('.//%st' % ns)
                                if texts:
                                    shared.append(''.join([t.text or '' for t in texts]))
                                else:
                                    shared.append(''.join(si.itertext()))
                        sheet_name = None
                        for name in namelist:
                            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                                sheet_name = name
                                break
                        if sheet_name is None:
                            raise Exception('worksheet not found')
                        sheet_xml = zf.read(sheet_name)
                        root = ET.fromstring(sheet_xml)
                        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                        for c in root.findall('.//%sc' % ns):
                            r = c.get('r')
                            if not r or not r.startswith('A'):
                                continue
                            v = c.find('%sv' % ns)
                            if v is None:
                                is_elem = c.find('%sis' % ns)
                                if is_elem is not None:
                                    t = is_elem.find('.//%st' % ns)
                                    if t is not None and t.text:
                                        names.append(t.text.strip())
                                continue
                            val = v.text or ''
                            if c.get('t') == 's':
                                try:
                                    idx = int(val)
                                    val = shared[idx] if idx < len(shared) else ''
                                except Exception:
                                    pass
                            if val.strip():
                                names.append(val.strip())
                except Exception as e:
                    self.log_append(f'Failed to read .xlsx: {e}')
            else:
                lines = try_read_text_lines(path)
                names = [ln.strip() for ln in lines if ln.strip()]
        except Exception as e:
            self.log_append(f'Error loading names: {e}')

        # if append requested, extend existing list, otherwise replace
        if append and self.names:
            before = len(self.names)
            self.names.extend(names)
            for n in names:
                self.name_list.addItem(n)
            self.log_append(f"Appended {len(names)} names from: {path} (total {before + len(names)})")
        else:
            self.names = names
            self.name_list.clear()
            for n in names:
                self.name_list.addItem(n)
            self.log_append(f"Loaded {len(names)} names from: {path}")

        self.update_preview()

    def sanitize_name(self, name):
        name = name.strip()
        name = MID_DOT_RE.sub('', name)
        name = ILLEGAL_CHARS_RE.sub('', name)
        return name

    def compute_final_candidates(self, pdf_paths, names):
        """Compute final candidate filenames (not full paths) with conflict resolution.
        Returns list of filenames same length as pdf_paths.
        """
        dirpath = os.path.dirname(pdf_paths[0]) if pdf_paths else self.pdf_folder or ''
        existing = set(safe_listdir(dirpath)) if dirpath else set()
        # Treat existing files as potential conflicts but allow if it's the source file itself
        src_basenames = [os.path.basename(p) for p in pdf_paths]
        candidates = []
        used = set()
        for i, src in enumerate(src_basenames):
            name = names[i] if i < len(names) else ''
            if not name:
                candidates.append('')
                continue
            base = self.sanitize_name(name)
            candidate = base + '.pdf'
            # avoid colliding with other candidates or existing files that are not current sources
            counter = 1
            while True:
                collides = False
                if candidate in existing and candidate not in src_basenames:
                    collides = True
                if candidate in used:
                    collides = True
                if not collides:
                    break
                candidate = f"{base} ({counter}).pdf"
                counter += 1
            candidates.append(candidate)
            used.add(candidate)
        return candidates

    def update_preview(self):
        # guard during shutdown
        if getattr(self, '_closing', False):
            return
        try:
            # ensure internal lists follow current widget order
            try:
                self.sync_lists_from_widgets()
            except Exception:
                pass
            self.preview.clear()
            items = []
            # use pdf_list widget order for display
            pdfs = [self.pdf_list.item(i).text() for i in range(self.pdf_list.count())]
            names = self.names
            # If counts match, show computed final candidates (with collision resolution)
            if len(pdfs) == len(names) and pdfs:
                candidates = self.compute_final_candidates(self.pdf_paths, names)
                for old, new in zip(pdfs, candidates):
                    items.append((old, new))
            else:
                for i, pdf in enumerate(pdfs):
                    right = names[i] if i < len(names) else ''
                    sanitized = (self.sanitize_name(right) + '.pdf') if right else ''
                    items.append((pdf, sanitized))
            for old, new in items:
                display = f"{old}  →  {new}" if new else f"{old}  →  (빈 이름)"
                self.preview.addItem(display)
            # if counts mismatch, show a highlighted warning item
            if len(self.pdf_paths) != len(self.names):
                self.preview.addItem(f"[주의] PDF 수: {len(self.pdf_paths)} / 이름 수: {len(self.names)} - 개수 불일치")
        except RuntimeError:
            # widget(s) likely deleted
            return
        except Exception:
            return

    # Methods to reorder items and sort
    def move_list_items(self, list_widget, data_list, direction):
        # direction: -1 up, +1 down
        selected = list_widget.selectedIndexes()
        if not selected:
            return
        # capture texts to preserve selection after move
        selected_texts = [list_widget.item(idx.row()).text() for idx in selected]
        rows = sorted(set(idx.row() for idx in selected))
        if direction == -1:
            if rows[0] == 0:
                return
        else:
            if rows[-1] == list_widget.count() - 1:
                return
        # Move items
        if direction == -1:
            for row in rows:
                item = list_widget.takeItem(row)
                list_widget.insertItem(row - 1, item)
        else:
            for row in reversed(rows):
                item = list_widget.takeItem(row)
                list_widget.insertItem(row + 1, item)
        # restore selection by text
        self.preserve_selection_by_text(list_widget, selected_texts)
        # After rearranging widget, rebuild internal lists
        self.sync_and_update()

    def move_pdf_up(self):
        self.move_list_items(self.pdf_list, self.pdf_paths, -1)

    def move_pdf_down(self):
        self.move_list_items(self.pdf_list, self.pdf_paths, 1)

    def move_name_up(self):
        self.move_list_items(self.name_list, self.names, -1)

    def move_name_down(self):
        self.move_list_items(self.name_list, self.names, 1)

    def move_pdf_top(self):
        self.move_selected_to_top(self.pdf_list)

    def move_pdf_bottom(self):
        self.move_selected_to_bottom(self.pdf_list)

    def move_pdf_to_position(self):
        self.move_selected_to_position(self.pdf_list)

    def move_name_top(self):
        self.move_selected_to_top(self.name_list)

    def move_name_bottom(self):
        self.move_selected_to_bottom(self.name_list)

    def move_name_to_position(self):
        self.move_selected_to_position(self.name_list)

    def move_selected_to_top(self, list_widget):
        selected = list_widget.selectedIndexes()
        if not selected:
            return
        selected_texts = [list_widget.item(idx.row()).text() for idx in selected]
        rows = sorted(set(idx.row() for idx in selected))
        for i, row in enumerate(rows):
            item = list_widget.takeItem(row - i)
            list_widget.insertItem(i, item)
        # restore selection
        self.preserve_selection_by_text(list_widget, selected_texts)
        self.sync_and_update()

    def move_selected_to_bottom(self, list_widget):
        selected = list_widget.selectedIndexes()
        if not selected:
            return
        selected_texts = [list_widget.item(idx.row()).text() for idx in selected]
        rows = sorted(set(idx.row() for idx in selected))
        # insert in reverse to preserve order
        count = list_widget.count()
        for i, row in enumerate(reversed(rows)):
            item = list_widget.takeItem(row)
            list_widget.insertItem(count - i, item)
        # restore selection
        self.preserve_selection_by_text(list_widget, selected_texts)
        self.sync_and_update()

    def move_selected_to_position(self, list_widget):
        selected = list_widget.selectedIndexes()
        if not selected:
            return
        selected_texts = [list_widget.item(idx.row()).text() for idx in selected]
        rows = sorted(set(idx.row() for idx in selected))
        # ask user for target index (1-based)
        target, ok = QInputDialog.getInt(self, '위치로 이동', '목표 인덱스 (1부터):', 1, 1, max(1, list_widget.count()))
        if not ok:
            return
        target_idx = target - 1
        # remove items then insert at target keeping relative order
        items = [list_widget.takeItem(r) for r in rows]
        # if target is after removed rows, adjust
        if target_idx > rows[0]:
            target_idx = target_idx - len(rows) + 1
        for i, item in enumerate(items):
            list_widget.insertItem(target_idx + i, item)
        # restore selection
        self.preserve_selection_by_text(list_widget, selected_texts)
        self.sync_and_update()

    def preserve_selection_by_text(self, list_widget, texts):
        # Clear and reselect items that match texts in order, avoiding duplicates
        list_widget.clearSelection()
        used = set()
        for i in range(list_widget.count()):
            it = list_widget.item(i)
            t = it.text()
            if t in texts and t not in used:
                it.setSelected(True)
                used.add(t)


    def sync_lists_from_widgets(self):
        # sync self.names from name_list widget
        self.names = [self.name_list.item(i).text() for i in range(self.name_list.count())]
        # sync pdf_paths order by basenames shown in widget
        basenames = [self.pdf_list.item(i).text() for i in range(self.pdf_list.count())]
        new_paths = []
        if self.pdf_folder:
            # assume files reside in the selected folder
            for bn in basenames:
                new_paths.append(os.path.join(self.pdf_folder, bn))
        else:
            # fallback: match against existing pdf_paths
            used = set()
            for bn in basenames:
                for p in self.pdf_paths:
                    if os.path.basename(p) == bn and p not in used:
                        new_paths.append(p)
                        used.add(p)
                        break
        if new_paths:
            self.pdf_paths = new_paths

    def sync_and_update(self):
        # avoid running during shutdown/after widgets deleted
        if getattr(self, '_closing', False):
            return
        try:
            self.sync_lists_from_widgets()
        except Exception:
            return
        try:
            self.update_preview()
        except Exception:
            return

    def rename_execute(self):
        if not self.pdf_paths:
            QMessageBox.warning(self, "경고", "PDF 파일이 로드되지 않았습니다.")
            return
        if not self.names:
            QMessageBox.warning(self, "경고", "이름 리스트가 로드되지 않았습니다.")
            return
        if len(self.pdf_paths) != len(self.names):
            QMessageBox.warning(self, "개수 불일치", "PDF 개수와 이름 개수가 다릅니다. 실행할 수 없습니다. 먼저 이름 수를 맞추거나 초과 이름을 삭제하세요.")
            return
        # confirm
        r = QMessageBox.question(self, "확인", f"총 {len(self.pdf_paths)}개의 파일명을 변경합니다. 진행하시겠습니까?", QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return

        # compute final candidates and show in log
        candidates = self.compute_final_candidates(self.pdf_paths, self.names)
        self.log_append("Final target names computed (conflicts resolved if any):")
        for s, t in zip(self.pdf_paths, candidates):
            self.log_append(f"  {os.path.basename(s)} -> {t}")

        ok = QMessageBox.question(self, "최종 확인", "위 이름으로 변경을 진행합니다. 계속하시겠습니까?", QMessageBox.Yes | QMessageBox.No)
        if ok != QMessageBox.Yes:
            return

        # perform transactional rename using safe_rename: rename src -> temp -> final. On any failure, attempt rollback.
        rename_map = []  # list of tuples (final_path, original_path)
        temp_map = []  # list of tuples (temp_path, original_path)
        temp_suffix = f".renametmp_{uuid.uuid4().hex}"
        success_count = 0
        fail_count = 0
        try:
            # Phase 1: rename originals to temp names
            for src in self.pdf_paths:
                dirname = os.path.dirname(src)
                basename = os.path.basename(src)
                temp_name = basename + temp_suffix
                temp_path = os.path.join(dirname, temp_name)
                # ensure unique temp
                counter = 1
                while safe_exists(temp_path):
                    temp_path = os.path.join(dirname, f"{basename}{temp_suffix}.{counter}")
                    counter += 1
                if not safe_rename(src, temp_path):
                    raise Exception(f"Failed to rename {src} to temp {temp_path}")
                temp_map.append((temp_path, src))
            # Phase 2: rename temps to final names
            for (temp_path, orig), target_name in zip(temp_map, candidates):
                dirname = os.path.dirname(orig)
                final_path = os.path.join(dirname, target_name)
                # ensure unique final (should be resolved already)
                base, ext = os.path.splitext(final_path)
                cnt = 1
                while safe_exists(final_path) and final_path not in [t for t, _ in temp_map]:
                    final_path = f"{base} ({cnt}){ext}"
                    cnt += 1
                if not safe_rename(temp_path, final_path):
                    raise Exception(f"Failed to rename temp {temp_path} to final {final_path}")
                rename_map.append((final_path, orig))
                self.log_append(f"OK: {os.path.basename(orig)} -> {os.path.basename(final_path)}")
                success_count += 1
        except Exception as e:
            self.log_append(f"Error during rename: {e}")
            fail_count += 1
            # rollback: move any temp files back to original names, and any already-final back if possible
            for temp_path, orig in temp_map:
                try:
                    if safe_exists(temp_path):
                        safe_rename(temp_path, orig)
                except Exception as ex:
                    self.log_append(f"Rollback failed for {temp_path} -> {orig}: {ex}")
            for final_path, orig in rename_map:
                try:
                    if safe_exists(final_path):
                        safe_rename(final_path, orig)
                except Exception as ex:
                    self.log_append(f"Rollback failed for {final_path} -> {orig}: {ex}")
        finally:
            self.last_rename_map = [(new, old) for (new, old) in rename_map]
            if self.last_rename_map:
                self.btn_undo.setEnabled(True)
            self.log_append(f"완료: 성공 {success_count}, 실패 {fail_count}")
            if self.pdf_folder:
                self.load_folder(self.pdf_folder)
            self.sync_and_update()

    def delete_selected_names(self):
        selected = self.name_list.selectedIndexes()
        if not selected:
            return
        rows = sorted(set(idx.row() for idx in selected), reverse=True)
        for r in rows:
            self.name_list.takeItem(r)
        self.sync_and_update()

    def closeEvent(self, event):
        # mark closing to avoid signal handlers running after widgets deleted
        self._closing = True
        try:
            super().closeEvent(event)
        except Exception:
            event.accept()

    def undo(self):
        if not self.last_rename_map:
            QMessageBox.information(self, "정보", "복구할 작업이 없습니다.")
            return
        # confirm
        r = QMessageBox.question(self, "Undo 확인", f"마지막 변경을 되돌립니다. 진행하시겠습니까?", QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        # Use transactional approach: move current files (new paths) to temp, then temp->original
        temp_suffix = f".undotmp_{uuid.uuid4().hex}"
        temp_map = []  # (temp_path, original_path)
        restored = 0
        failed = 0
        try:
            # Phase 1: move all current 'new' files to temps to avoid name collisions
            for new, old in self.last_rename_map:
                if safe_exists(new):
                    dirname = os.path.dirname(new)
                    base = os.path.basename(new)
                    temp_path = os.path.join(dirname, base + temp_suffix)
                    cnt = 1
                    while safe_exists(temp_path):
                        temp_path = os.path.join(dirname, f"{base}{temp_suffix}.{cnt}")
                        cnt += 1
                    if not safe_rename(new, temp_path):
                        self.log_append(f"UNDO EXC: {new} -> temp {temp_path} : rename failed")
                        failed += 1
                    else:
                        temp_map.append((temp_path, old))
                else:
                    self.log_append(f"UNDO WARN: 대상 없음 {new}")
                    failed += 1
            # Phase 2: move temps to original paths
            for temp_path, orig in temp_map:
                # if orig exists (unexpected), try to avoid overwrite: if orig is among temps, it's okay
                if safe_exists(orig):
                    # if some other temp will become orig later, allow; otherwise, cannot overwrite
                    # check if orig is one of the temp target originals (i.e., in list of olds)
                    olds = [o for _, o in self.last_rename_map]
                    if orig not in olds:
                        self.log_append(f"UNDO EXC: target exists {orig}, skipping")
                        failed += 1
                        # attempt to move temp back to its previous name? leave temp as-is
                        continue
                # ensure unique final if needed
                final_path = orig
                cnt = 1
                base, ext = os.path.splitext(final_path)
                while safe_exists(final_path) and final_path not in [t for t, _ in temp_map]:
                    final_path = f"{base} ({cnt}){ext}"
                    cnt += 1
                if not safe_rename(temp_path, final_path):
                    self.log_append(f"UNDO EXC: {temp_path} -> {final_path} : rename failed")
                    failed += 1
                else:
                    self.log_append(f"UNDO: {os.path.basename(final_path)} -> {os.path.basename(final_path)}")
                    restored += 1
        except Exception as e:
            self.log_append(f"UNDO ERROR: {e}")
        finally:
            self.last_rename_map = None
            self.btn_undo.setEnabled(False)
            self.log_append(f"Undo 완료: 복구 {restored}, 실패 {failed}")
            if self.pdf_folder:
                self.load_folder(self.pdf_folder)


def main():
    # Enable High DPI scaling where supported
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    except Exception:
        pass
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
