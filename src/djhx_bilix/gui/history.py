"""GUI-only projection of immutable session events into a compact tree."""

from collections import Counter
from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from djhx_bilix.feedback import TransferEstimator, feedback_text, format_eta, format_speed

STATES = {
    "queued": "等待",
    "loading": "读取中",
    "discovered": "已读取",
    "downloading": "下载中",
    "checking_video": "校验视频",
    "checking_audio": "校验音频",
    "muxing": "合并音视频",
    "committing": "保存文件",
    "completed": "已完成",
    "skipped": "已存在，跳过未校验",
    "failed": "失败",
    "canceled": "已取消",
}
NODE_ROLE = Qt.ItemDataRole.UserRole
STATE_ROLE = Qt.ItemDataRole.UserRole + 1
STREAMS_ROLE = Qt.ItemDataRole.UserRole + 2
FEEDBACK_ROLE = Qt.ItemDataRole.UserRole + 3


@dataclass(eq=False)
class Row:
    kind: str
    identity: str
    row: int
    parent: "Row | None" = None
    children: list = field(default_factory=list)
    title: str = ""
    state: str = "queued"
    progress: str = ""
    detail: str = ""
    attempt: int = 0
    counts: Counter = field(default_factory=Counter)
    streams: dict = field(default_factory=dict)
    superseded: bool = False
    estimator: TransferEstimator | None = None
    feedback: str = ""
    paused: bool = False


class HistoryModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.roots = []
        self.sources = {}
        self.tasks = {}
        self.counts = Counter()

    def index(self, row, column, parent=QModelIndex()):
        if parent.isValid() and parent.column() != 0:
            return QModelIndex()
        rows = parent.internalPointer().children if parent.isValid() else self.roots
        if 0 <= row < len(rows) and 0 <= column < 4:
            return self.createIndex(row, column, rows[row])
        return QModelIndex()

    def parent(self, index):
        if index.isValid() and (parent := index.internalPointer().parent) is not None:
            return self.createIndex(parent.row, 0, parent)
        return QModelIndex()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid() and parent.column() != 0:
            return 0
        return len(parent.internalPointer().children if parent.isValid() else self.roots)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ("视频 / 选集", "状态", "进度", "操作")[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.internalPointer()
        if role == NODE_ROLE:
            return row
        if role == STATE_ROLE:
            return row.state
        if role == STREAMS_ROLE:
            return row.streams
        if role == FEEDBACK_ROLE:
            return row.feedback
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            palette = QApplication.palette()
            dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
            if palette.color(QPalette.ColorRole.Highlight).name() == "#ffff00":
                return palette.color(QPalette.ColorRole.Text)
            colors = {
                "completed": "#75dba1" if dark else "#13713d",
                "failed": "#ff9292" if dark else "#b12626",
                "skipped": "#aeb7c3" if dark else "#59616b",
                "canceled": "#aeb7c3" if dark else "#59616b",
            }
            return QColor(colors[row.state]) if row.state in colors else None
        if index.column() == 3:
            return "快捷操作；右侧更多菜单" if role == Qt.ItemDataRole.ToolTipRole else None
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.column() == 2 and row.estimator is not None:
                value = row.estimator.snapshot()
                return "\n".join(
                    [
                        feedback_text(value),
                        *(
                            f"{'视频' if s.stream == 'video' else '音频'} · "
                            f"{format_speed(s.speed)} · "
                            f"{format_eta(s.eta)}"
                            for s in value.streams
                        ),
                    ]
                )
            return row.title if index.column() == 0 else row.detail or STATES.get(row.state, "")
        if role == Qt.ItemDataRole.DisplayRole:
            if row.children:
                done = sum(row.counts[s] for s in ("completed", "skipped", "failed", "canceled"))
                values = (
                    f"{row.title} · {len(row.children)} 集",
                    f"已结束 {done} / {len(row.children)}",
                    "",
                )
            else:
                state = STATES.get(row.state, row.state)
                if row.paused:
                    state = "已暂停" if row.feedback == "已暂停" else "暂停中（处理阶段结束后等待）"
                symbols = {
                    "completed": "✓ ",
                    "skipped": "! ",
                    "failed": "× ",
                    "canceled": "— ",
                    "queued": "· ",
                }
                state = symbols.get(row.state, "● ") + state
                values = (row.title, state, "" if row.streams else row.progress)
            return values[index.column()]

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def row_index(self, row, column=0):
        return self.createIndex(row.row, column, row)

    def source(self, request):
        original = self.sources.get(request.origin_request_id)
        if original and not original.children:
            original.superseded = True
            self.dataChanged.emit(self.row_index(original), self.row_index(original, 2))
        row = self.sources.get(request.request_id)
        if row is None:
            position = len(self.roots)
            self.beginInsertRows(QModelIndex(), position, position)
            row = Row("source", request.request_id, position, title=request.spec.source)
            self.roots.append(row)
            self.sources[row.identity] = row
            self.endInsertRows()
        row.state = request.state
        row.detail = f"{request.detail} {request.action}".strip()
        self.dataChanged.emit(self.row_index(row), self.row_index(row, 2))
        return row

    def task(
        self, task, attempt, request, *, title=None, progress=None, streams=None, samples=None
    ):
        row = self.tasks.get(task.task_id)
        state_changed = row is None or row.state != attempt.state
        if row is None:
            parent = self.sources.get(request.request_id) or self.source(request)
            position = len(parent.children)
            self.beginInsertRows(self.row_index(parent), position, position)
            row = Row(
                "task", task.task_id, position, parent, title=f"P{task.spec.page} · {task.label}"
            )
            parent.children.append(row)
            self.tasks[row.identity] = row
            self.endInsertRows()
        else:
            row.parent.counts[row.state] -= 1
            self.counts[row.state] -= 1
        row.state, row.attempt = attempt.state, attempt.number
        row.paused = attempt.paused and attempt.state not in {
            "completed",
            "skipped",
            "failed",
            "canceled",
        }
        row.parent.counts[row.state] += 1
        self.counts[row.state] += 1
        if title:
            row.title = f"P{task.spec.page} · {title}"
            row.parent.title = title
        row.detail = f"{attempt.detail} {attempt.action}".strip()
        if progress is not None:
            row.progress = progress
        elif attempt.state != "downloading":
            row.progress = ""
        if streams is not None:
            row.streams = dict(streams)
        elif attempt.state != "downloading":
            row.streams = {}
        if samples and attempt.state == "downloading":
            if row.estimator is None:
                row.estimator = TransferEstimator()
            for sample in samples:
                row.estimator.ingest(sample)
            row.feedback = (
                "已暂停"
                if any(s.phase == "paused" for s in row.estimator.snapshot().streams)
                else feedback_text(row.estimator.snapshot())
            )
            # Session event emission and stream sampling may arrive in different orders.
            row.streams = {
                s.stream: (s.completed, s.total or (s.completed if s.phase == "finished" else None))
                for s in row.estimator.snapshot().streams
            }
        elif attempt.state != "downloading":
            row.estimator, row.feedback = None, ""
        roles = [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole]
        roles.append(Qt.ItemDataRole.ForegroundRole)
        if state_changed:
            roles.append(STATE_ROLE)
        self.dataChanged.emit(self.row_index(row), self.row_index(row, 3), roles)
        self.dataChanged.emit(
            self.row_index(row.parent),
            self.row_index(row.parent, 1),
            [Qt.ItemDataRole.DisplayRole],
        )
        return row

    def refresh_feedback(self, row):
        row.feedback = feedback_text(row.estimator.snapshot())
        self.dataChanged.emit(
            self.row_index(row, 2),
            self.row_index(row, 2),
            [FEEDBACK_ROLE, Qt.ItemDataRole.ToolTipRole],
        )

    def rebuild(self, session):
        self.beginResetModel()
        self.roots, self.sources, self.tasks, self.counts = [], {}, {}, Counter()
        self.endResetModel()
        for request in session.requests.values():
            # Cleared discovered sources have no visible work left.
            if request.state != "discovered" or any(
                t.request_id == request.request_id for t in session.tasks.values()
            ):
                self.source(request)
        for task in session.tasks.values():
            self.task(task, task.latest, session.requests[task.request_id], title=task.label)


class HistoryFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "all"
        self.setRecursiveFilteringEnabled(True)
        self.setFilterRole(STATE_ROLE)
        self.setDynamicSortFilter(False)
        self._refresh = QTimer(self)
        self._refresh.setSingleShot(True)
        self._refresh.setInterval(35)
        self._refresh.timeout.connect(lambda: self.set_state(self.state))

    def setSourceModel(self, model):
        super().setSourceModel(model)
        model.dataChanged.connect(self._schedule)
        model.rowsInserted.connect(lambda *_args: self._schedule())

    def _schedule(self, top=None, bottom=None, roles=None):
        if (not roles or STATE_ROLE in roles) and not self._refresh.isActive():
            self._refresh.start()

    def set_state(self, state):
        self._refresh.stop()
        self.beginFilterChange()
        self.state = state
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        node = model.data(index, NODE_ROLE)
        if node.superseded:
            return False
        if self.state == "all":
            return True
        if node.children:
            return False  # Recursive filtering keeps only parents of matching children.
        state = node.state
        return (
            state == self.state
            or self.state == "success"
            and state in {"completed", "skipped"}
            or self.state == "active"
            and state not in {"completed", "skipped", "failed", "canceled", "discovered"}
        )
