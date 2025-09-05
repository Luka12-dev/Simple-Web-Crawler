import sys
import time
import json
import csv
import re
from dataclasses import dataclass, asdict
from typing import Dict, Set, List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QPlainTextEdit, QFileDialog, QMessageBox, QComboBox
)

try:
    import requests
except Exception:
    requests = None

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# Data models

@dataclass
class NodeInfo:
    url: str
    status: Optional[int] = None
    accepts_params: bool = False
    param_examples: List[str] = None
    out_degree: int = 0

    def to_dict(self):
        return {
            'url': self.url,
            'status': self.status,
            'accepts_params': self.accepts_params,
            'param_examples': self.param_examples or [],
            'out_degree': self.out_degree
        }

# Helper functions

def canonicalize(url: str) -> str:
    """Return canonical URL without query and fragment (used for node identity)."""
    p = urlparse(url)
    path = p.path or '/'
    # remove duplicate slashes
    path = re.sub(r'/+', '/', path)
    canon = urlunparse((p.scheme, p.netloc, path.rstrip('/') or '/', '', '', ''))
    return canon

def strip_fragment(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path or '', p.params, p.query, ''))

def has_query(url: str) -> bool:
    return bool(urlparse(url).query)

# Crawler Worker

class CrawlerWorker(QThread):
    progress = pyqtSignal(object)  # emits (NodeInfo or (from_url, to_url))
    finished_all = pyqtSignal(dict, dict)  # nodes, adjacency
    log = pyqtSignal(str)

    def __init__(self, start_url: str, max_pages: int, max_depth: int, same_domain: bool,
                 detect_params: bool, delay: float, timeout: int, parent=None):
        super().__init__(parent)
        self.start_url = start_url
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.same_domain = same_domain
        self.detect_params = detect_params
        self.delay = delay
        self.timeout = timeout
        self._nodes: Dict[str, NodeInfo] = {}
        self._adj: Dict[str, Set[str]] = {}
        self._session = requests.Session() if requests else None

    def run(self):
        if requests is None or BeautifulSoup is None:
            self.log.emit('ERROR: missing dependencies. Install `requests` and `beautifulsoup4`.')
            self.finished_all.emit({}, {})
            return

        parsed_start = urlparse(self.start_url)
        base_domain = parsed_start.netloc

        queue: List[Tuple[str, int]] = []  # (url, depth)
        start_canon = canonicalize(self.start_url)
        queue.append((self.start_url, 0))
        visited: Set[str] = set()

        while queue and len(visited) < self.max_pages:
            url, depth = queue.pop(0)
            if depth > self.max_depth:
                continue

            norm = strip_fragment(url)
            canon = canonicalize(norm)
            if canon in visited:
                continue
            # domain filter
            if self.same_domain:
                if urlparse(url).netloc != base_domain:
                    self.log.emit(f'Skipping external domain: {url}')
                    visited.add(canon)
                    continue

            self.log.emit(f'Fetching ({len(visited)+1}/{self.max_pages}) depth={depth}: {url}')
            try:
                resp = self._session.get(url, timeout=self.timeout, allow_redirects=True)
                status = resp.status_code
                content_type = resp.headers.get('Content-Type', '')
                text = resp.text if resp.text else ''
            except Exception as e:
                status = None
                content_type = ''
                text = ''
                self.log.emit(f'ERROR fetching {url}: {e}')

            node = NodeInfo(url=canon, status=status, accepts_params=False, param_examples=[], out_degree=0)
            self._nodes[canon] = node
            self._adj.setdefault(canon, set())
            visited.add(canon)
            self.progress.emit(node)

            # detect parameters by query string
            if self.detect_params and has_query(url):
                node.accepts_params = True
                node.param_examples.append(url)
                self.log.emit(f'Params detected in URL: {url}')

            # parse HTML only for text/html
            if 'html' in content_type.lower() and text:
                try:
                    soup = BeautifulSoup(text, 'html.parser')

                    # find links
                    anchors = soup.find_all('a', href=True)
                    for a in anchors:
                        href = a.get('href')
                        if href.startswith('mailto:') or href.startswith('javascript:'):
                            continue
                        abs_url = urljoin(resp.url, href)
                        abs_url = strip_fragment(abs_url)
                        to_canon = canonicalize(abs_url)
                        # add edge
                        self._adj[canon].add(to_canon)
                        self.progress.emit((canon, to_canon))

                        # if link has query -> mark target as accepting params
                        if self.detect_params and has_query(abs_url):
                            self._nodes.setdefault(to_canon, NodeInfo(url=to_canon, param_examples=[]))
                            self._nodes[to_canon].accepts_params = True
                            self._nodes[to_canon].param_examples = self._nodes[to_canon].param_examples or []
                            self._nodes[to_canon].param_examples.append(abs_url)

                        # enqueue if not visited
                        if to_canon not in visited and len(visited) + len(queue) < self.max_pages:
                            queue.append((abs_url, depth + 1))

                    # find forms (this often indicates parameters)
                    forms = soup.find_all('form')
                    for f in forms:
                        action = f.get('action') or resp.url
                        method = (f.get('method') or 'GET').upper()
                        abs_action = urljoin(resp.url, action)
                        abs_action = strip_fragment(abs_action)
                        action_canon = canonicalize(abs_action)
                        # collect input names
                        inputs = [inp.get('name') for inp in f.find_all(['input', 'select', 'textarea']) if inp.get('name')]
                        example = abs_action
                        if inputs:
                            # create a sample query string or note for POST
                            if method == 'GET':
                                qs = '&'.join([f'{n}=example' for n in inputs])
                                example = abs_action + ('?' if '?' not in abs_action else '&') + qs
                            else:
                                example = f'{method} form -> {abs_action} params: {",".join(inputs)}'

                        self._adj[canon].add(action_canon)
                        self.progress.emit((canon, action_canon))

                        self._nodes.setdefault(action_canon, NodeInfo(url=action_canon, param_examples=[]))
                        self._nodes[action_canon].accepts_params = True
                        self._nodes[action_canon].param_examples = self._nodes[action_canon].param_examples or []
                        self._nodes[action_canon].param_examples.append(example)

                        if action_canon not in visited and len(visited) + len(queue) < self.max_pages:
                            queue.append((abs_action, depth + 1))

                except Exception as e:
                    self.log.emit(f'HTML parse error for {url}: {e}')

            # update out-degree
            for k, s in self._adj.items():
                if k in self._nodes:
                    self._nodes[k].out_degree = len(s)

            # delay
            if self.delay:
                time.sleep(self.delay)

        # finalize
        self.log.emit('Crawl finished.')
        # ensure every node exists in nodes dictionary
        for n in list(self._adj.keys()):
            self._nodes.setdefault(n, NodeInfo(url=n, param_examples=[]))
            self._nodes[n].out_degree = len(self._adj.get(n, []))

        self.finished_all.emit(self._nodes, {k: list(v) for k, v in self._adj.items()})

# GUI

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Simple Web Crawler')
        self.setWindowIcon(QIcon('web8.ico'))
        self.resize(1100, 720)
        self._setup_ui()
        self._apply_styles()
        self.worker: Optional[CrawlerWorker] = None
        self.nodes: Dict[str, NodeInfo] = {}
        self.adj: Dict[str, List[str]] = {}

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        grid = QGridLayout()
        central.setLayout(grid)

        grid.addWidget(QLabel('Start URL:'), 0, 0)
        self.url_edit = QLineEdit('https://example.com')
        grid.addWidget(self.url_edit, 0, 1, 1, 4)

        grid.addWidget(QLabel('Max pages:'), 1, 0)
        self.max_pages_spin = QSpinBox()
        self.max_pages_spin.setRange(1, 5000)
        self.max_pages_spin.setValue(200)
        grid.addWidget(self.max_pages_spin, 1, 1)

        grid.addWidget(QLabel('Max depth:'), 1, 2)
        self.max_depth_spin = QSpinBox()
        self.max_depth_spin.setRange(0, 50)
        self.max_depth_spin.setValue(3)
        grid.addWidget(self.max_depth_spin, 1, 3)

        self.same_domain_cb = QCheckBox('Restrict to same domain')
        self.same_domain_cb.setChecked(True)
        grid.addWidget(self.same_domain_cb, 2, 0, 1, 2)

        self.detect_params_cb = QCheckBox('Detect endpoints that accept parameters')
        self.detect_params_cb.setChecked(True)
        grid.addWidget(self.detect_params_cb, 2, 2, 1, 2)

        grid.addWidget(QLabel('Delay between requests (s):'), 3, 0)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 10)
        self.delay_spin.setValue(0)
        grid.addWidget(self.delay_spin, 3, 1)

        grid.addWidget(QLabel('Timeout (s):'), 3, 2)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 60)
        self.timeout_spin.setValue(10)
        grid.addWidget(self.timeout_spin, 3, 3)

        self.start_btn = QPushButton('Start Crawl')
        grid.addWidget(self.start_btn, 1, 4, 2, 1)
        self.start_btn.clicked.connect(self.on_start)

        # Table of nodes
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['URL', 'Status', 'Accepts Params', 'Param Examples', 'Out-degree'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        grid.addWidget(self.table, 4, 0, 1, 6)

        # Log area
        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        grid.addWidget(self.log_area, 5, 0, 1, 6)

        # Export and graph
        self.export_csv_btn = QPushButton('Export CSV')
        self.export_json_btn = QPushButton('Export JSON')
        self.draw_graph_btn = QPushButton('Draw Graph (optional)')
        grid.addWidget(self.export_csv_btn, 6, 3)
        grid.addWidget(self.export_json_btn, 6, 4)
        grid.addWidget(self.draw_graph_btn, 6, 5)

        self.export_csv_btn.clicked.connect(self.on_export_csv)
        self.export_json_btn.clicked.connect(self.on_export_json)
        self.draw_graph_btn.clicked.connect(self.on_draw_graph)

    def _apply_styles(self):
        self.setStyleSheet('''
            QMainWindow { background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1, stop:0 #071025, stop:1 #08111b); }
            QLabel { color: #e6eef8; font-weight: 600; }
            QLineEdit, QSpinBox, QPlainTextEdit {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.06);
                color: #e6eef8;
                padding: 6px;
                border-radius: 8px;
            }
            QTableWidget { background: rgba(255,255,255,0.02); color: #e6eef8; }
            QPushButton { background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #7c3aed); color: white; padding: 8px; border-radius: 10px; }
            QPushButton:hover { opacity: 0.9; }
            QHeaderView::section { background: rgba(255,255,255,0.04); color: #cfeafe; padding: 6px; }
        ''')

    # Handlers

    def on_start(self):
        if requests is None or BeautifulSoup is None:
            QMessageBox.critical(self, 'Missing dependency', 'Install `requests` and `beautifulsoup4` (pip install requests beautifulsoup4).')
            return
        start_url = self.url_edit.text().strip()
        if not start_url:
            QMessageBox.warning(self, 'Input required', 'Please enter a starting URL.')
            return
        max_pages = int(self.max_pages_spin.value())
        max_depth = int(self.max_depth_spin.value())
        same_domain = bool(self.same_domain_cb.isChecked())
        detect_params = bool(self.detect_params_cb.isChecked())
        delay = float(self.delay_spin.value())
        timeout = int(self.timeout_spin.value())

        self.table.setRowCount(0)
        self.log_area.clear()
        self.nodes = {}
        self.adj = {}

        self.worker = CrawlerWorker(start_url=start_url, max_pages=max_pages, max_depth=max_depth,
                                    same_domain=same_domain, detect_params=detect_params,
                                    delay=delay, timeout=timeout)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_all.connect(self.on_finished_all)
        self.worker.log.connect(self._append_log)
        self.start_btn.setEnabled(False)
        self._append_log('Starting crawl...')
        self.worker.start()

    def on_progress(self, data):
        # data can be NodeInfo or (from, to)
        if isinstance(data, tuple) and len(data) == 2:
            frm, to = data
            # ensure nodes exist
            self.adj.setdefault(frm, set()).add(to)
            self.adj.setdefault(to, set())
            # update out-degree cell if node already present
            self._update_table_row(frm)
            self._update_table_row(to)
        elif isinstance(data, NodeInfo):
            self.nodes[data.url] = data
            self._upsert_table_row(data)

    def _upsert_table_row(self, node: NodeInfo):
        # find if URL exists in table
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0) and self.table.item(r, 0).text() == node.url:
                # update
                self.table.setItem(r, 1, QTableWidgetItem(str(node.status)))
                self.table.setItem(r, 2, QTableWidgetItem('Yes' if node.accepts_params else 'No'))
                examples = '\n'.join(node.param_examples or [])
                self.table.setItem(r, 3, QTableWidgetItem(examples))
                self.table.setItem(r, 4, QTableWidgetItem(str(node.out_degree)))
                return
        # insert new row
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(node.url))
        self.table.setItem(r, 1, QTableWidgetItem(str(node.status)))
        self.table.setItem(r, 2, QTableWidgetItem('Yes' if node.accepts_params else 'No'))
        examples = '\n'.join(node.param_examples or [])
        self.table.setItem(r, 3, QTableWidgetItem(examples))
        self.table.setItem(r, 4, QTableWidgetItem(str(node.out_degree)))

    def _update_table_row(self, url: str):
        # ensure node exists in nodes dict
        node = self.nodes.get(url)
        if not node:
            node = NodeInfo(url=url, param_examples=[])
            self.nodes[url] = node
        node.out_degree = len(self.adj.get(url, []))
        self._upsert_table_row(node)

    def on_finished_all(self, nodes: Dict[str, NodeInfo], adj: Dict[str, List[str]]):
        self.start_btn.setEnabled(True)
        self.nodes = nodes
        self.adj = {k: set(v) for k, v in adj.items()}
        # update table to reflect final out-degrees
        for url in self.adj.keys():
            self._update_table_row(url)
        self._append_log(f'Crawl finished. Nodes: {len(self.nodes)} Edges: {sum(len(v) for v in self.adj.values())}')

    def _append_log(self, text: str):
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        self.log_area.appendPlainText(f'[{ts}] {text}')

    def on_export_csv(self):
        if not self.nodes:
            QMessageBox.information(self, 'No results', 'No crawl results to export.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save CSV', 'crawl_results.csv', 'CSV Files (*.csv)')
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['url', 'status', 'accepts_params', 'param_examples', 'out_degree'])
            for n in self.nodes.values():
                writer.writerow([n.url, n.status, n.accepts_params, json.dumps(n.param_examples or []), n.out_degree])
        QMessageBox.information(self, 'Saved', f'CSV saved to {path}')

    def on_export_json(self):
        if not self.nodes:
            QMessageBox.information(self, 'No results', 'No crawl results to export.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save JSON', 'crawl_results.json', 'JSON Files (*.json)')
        if not path:
            return
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({u: n.to_dict() for u, n in self.nodes.items()}, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, 'Saved', f'JSON saved to {path}')

    def on_draw_graph(self):
        try:
            import networkx as nx
            import matplotlib.pyplot as plt
        except Exception:
            QMessageBox.information(self, 'Missing libs', 'Install optional libraries: networkx, matplotlib (pip install networkx matplotlib)')
            return
        G = nx.DiGraph()
        for u, node in self.nodes.items():
            G.add_node(u, accepts_params=node.accepts_params)
        for u, targets in self.adj.items():
            for v in targets:
                G.add_edge(u, v)
        plt.figure(figsize=(12, 8))
        pos = nx.spring_layout(G, k=0.5, iterations=50)
        nx.draw(G, pos, with_labels=False, node_size=100)
        # draw labels separately to avoid overlap
        for n, (x, y) in pos.items():
            plt.text(x, y, n.replace('https://', '').replace('http://', ''), fontsize=8)
        plt.title('Crawl graph')
        plt.show()

# Main

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()