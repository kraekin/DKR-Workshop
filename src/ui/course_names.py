"""Dedicated course-name window, with isolated drafts and atomic project edits."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
    QLabel,QLineEdit,QTreeWidget,QTreeWidgetItem,QHeaderView,QSplitter,QPushButton,
    QPlainTextEdit,QTabWidget,QDialogButtonBox)

from src.core.editing import EditSession
from src.core.rom import AssetType
from src.core.course_names import (NameRecord,NamePlan,EDITABLE_LANGUAGES,edit_names,
    name_warnings,plan_names)

ROLE=Qt.ItemDataRole.UserRole


class CourseNamesDialog(QDialog):
    names_changed=Signal()
    history_requested=Signal(bool)

    def __init__(self,session: EditSession,selected: int=0,parent: QWidget | None=None) -> None:
        super().__init__(parent)
        self.setObjectName('courseNamesDialog');self.setWindowTitle('Course Names — USA Rev 1')
        self.resize(1120,830)
        self.session=session;self.plan:NamePlan | None=None
        self.drafts:dict[int,dict[str,str]]={};self._loading=False
        self.current=selected
        layout=QVBoxLayout(self)
        intro=QLabel('Edit course names for tracks, hubs, bosses and other existing levels. '
            'Preview and Apply pending names, then save your project and export a ROM normally. '
            'Closing this window discards unapplied drafts.',self)
        intro.setWordWrap(True);layout.addWidget(intro)
        split=QSplitter(self);layout.addWidget(split,1)
        left=QWidget(split);col=QVBoxLayout(left);col.setContentsMargins(0,0,6,0)
        self.search=QLineEdit(left);self.search.setPlaceholderText('Filter name, ID or type…');self.search.setAccessibleName('Filter course names');col.addWidget(self.search)
        self.list=QTreeWidget(left);self.list.setObjectName('courseNameList')
        self.list.setHeaderLabels(('ID','Course / draft','Type'));self.list.setRootIsDecorated(False)
        self.list.header().setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        self.list.header().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.list.header().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        col.addWidget(self.list,1)
        right=QWidget(split);form=QVBoxLayout(right);form.setContentsMargins(6,0,0,0)
        self.caption=QLabel(right);self.caption.setTextFormat(Qt.TextFormat.PlainText);self.caption.setWordWrap(True);form.addWidget(self.caption)
        fields=QFormLayout();form.addLayout(fields)
        self.fields:dict[str,QLineEdit]={};self.widths:dict[str,QLabel]={}
        for key in EDITABLE_LANGUAGES:
            group=QWidget(right);row=QVBoxLayout(group);row.setContentsMargins(0,0,0,6)
            line=QLineEdit(group);line.setObjectName('courseName'+key.title());line.setAccessibleName('Course name '+key.title())
            # Let overlong input be entered so validation explains it instead of
            # silently truncating pasted names at the game's63-byte boundary.
            line.setMaxLength(4096);line.textChanged.connect(self._edited)
            metrics=QLabel(group);metrics.setWordWrap(True)
            row.addWidget(line);row.addWidget(metrics);fields.addRow(key.title(),group)
            self.fields[key]=line;self.widths[key]=metrics
        self.japanese=QLineEdit(right);self.japanese.setReadOnly(True);self.japanese.setAccessibleName('Japanese course name preserved')
        self.japanese.setToolTip('Original DKRJP bytes are retained. This USA Rev1 window edits only names using its Latin fonts.')
        fields.addRow('Japanese (preserved)',self.japanese)
        note=QLabel('Changed names: up to 63 ASCII bytes, using glyphs present in the game’s title, banner and small fonts. '
            'These fonts omit some punctuation and digits. Stored Japanese names are read-only. Language availability depends on the game.',right)
        note.setWordWrap(True);form.addWidget(note)
        row=QHBoxLayout();form.addLayout(row)
        self.original=QPushButton('Restore original names (draft)',right);self.original.clicked.connect(self._restore_original);row.addWidget(self.original)
        self.reset=QPushButton('Reset pending for this course',right);self.reset.clicked.connect(self._reset_course);row.addWidget(self.reset)
        tabs=QTabWidget(right);form.addWidget(tabs,1)
        self.changes=QPlainTextEdit(right);self.changes.setReadOnly(True);tabs.addTab(self.changes,'Pending changes')
        self.budget=QPlainTextEdit(right);self.budget.setReadOnly(True);tabs.addTab(self.budget,'ROM budget')
        self.message=QLabel(right);self.message.setTextFormat(Qt.TextFormat.PlainText);self.message.setWordWrap(True);form.addWidget(self.message)
        split.setSizes([420,680])
        bottom=QHBoxLayout();layout.addLayout(bottom)
        self.undo=QPushButton('Undo project edit',self);self.undo.clicked.connect(lambda:self._history(False));bottom.addWidget(self.undo)
        self.redo=QPushButton('Redo project edit',self);self.redo.clicked.connect(lambda:self._history(True));bottom.addWidget(self.redo)
        bottom.addStretch(1)
        self.preview=QPushButton('Preview name changes',self);self.preview.setObjectName('previewCourseNames');self.preview.clicked.connect(self.build_preview);bottom.addWidget(self.preview)
        self.apply=QPushButton('Apply pending names',self);self.apply.setObjectName('applyCourseNames');self.apply.clicked.connect(self._apply);bottom.addWidget(self.apply)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close,self);close.rejected.connect(self.reject);bottom.addWidget(close)
        self.search.textChanged.connect(self._filter)
        self.list.currentItemChanged.connect(self._selected)
        self.reload()
        # A name field owns Enter; do not invoke a destructive draft button.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)

    def reload(self) -> None:
        self._loading=True;self.list.clear()
        for level in self.session._catalog.levels:
            item=QTreeWidgetItem([str(level.index),level.name,level.header.category]);item.setData(0,ROLE,level.index)
            self.list.addTopLevelItem(item)
            if level.index==self.current:self.list.setCurrentItem(item)
        self._loading=False;self._load_fields();self._filter();self._invalidate()

    def _load_fields(self) -> None:
        self._loading=True
        names=self.session.course_names(self.current);draft=self.drafts.get(self.current,{})
        for key,line in self.fields.items():line.setText(draft.get(key,getattr(names,key)))
        self.japanese.setText(names.japanese)
        self.caption.setText(f'Course {self.current} · original ROM name: '+NameRecord.parse(self.session.original_asset(AssetType.LEVEL_NAMES,self.current)).values.english)
        self._loading=False;self._metrics()

    def _selected(self,item: QTreeWidgetItem | None,*_: object) -> None:
        if self._loading or item is None:return
        self.current=int(item.data(0,ROLE));self._load_fields()
        self._invalidate()

    def _filter(self,*_: object) -> None:
        query=self.search.text().strip().casefold()
        for i in range(self.list.topLevelItemCount()):
            item=self.list.topLevelItem(i);index=int(item.data(0,ROLE));names=self.session.course_names(index)
            text=' '.join((item.text(0),item.text(1),item.text(2),names.german,names.french,names.japanese,*self.drafts.get(index,{}).values()))
            item.setHidden(query not in text.casefold())

    def _edited(self,*_: object) -> None:
        if self._loading:return
        names=self.session.course_names(self.current)
        values={k:line.text() for k,line in self.fields.items()}
        if all(getattr(names,k)==v for k,v in values.items()):self.drafts.pop(self.current,None)
        else:self.drafts[self.current]=values
        item=self.list.currentItem()
        if item is not None:item.setText(1,(values['english'] or f'Level {self.current}')+(' *' if self.current in self.drafts else ''))
        self._metrics();self._invalidate()

    def _metrics(self) -> None:
        for key,line in self.fields.items():
            text=line.text();f=self.session.name_fonts
            self.widths[key].setText(f'{len(text)} / 63 bytes · title {f[2].width(text)} px · banner {f[0].width(text)} px · small {f[1].width(text)} px')
        try:
            raw=edit_names(self.session.original_asset(AssetType.LEVEL_NAMES,self.current),self.session.current_asset(AssetType.LEVEL_NAMES,self.current),
                {k:line.text() for k,line in self.fields.items()},self.session.name_fonts)
            warnings=name_warnings(NameRecord.parse(raw),self.session.name_fonts)
            self.message.setText('\n'.join(warnings) or 'Choose Preview name changes to review the staged names and ROM budget.')
            self.message.setStyleSheet('color: #fbbf24;' if warnings else '')
        except ValueError as error:
            self.message.setText(str(error));self.message.setStyleSheet('color: #fca5a5;')

    def _invalidate(self) -> None:
        self.plan=None;self.apply.setEnabled(False);self.budget.clear()
        self.changes.setPlainText('\n\n'.join(f'Course {i}\n'+'\n'.join(f'{key.title()}: {getattr(self.session.course_names(i),key)!r} → {value!r}'
            for key,value in values.items() if getattr(self.session.course_names(i),key)!=value) for i,values in sorted(self.drafts.items())) or 'No pending name changes.')
        self.preview.setEnabled(bool(self.drafts));self.reset.setEnabled(self.current in self.drafts)
        self.undo.setEnabled(not self.drafts and self.session.can_undo);self.redo.setEnabled(not self.drafts and self.session.can_redo)
        self.undo.setToolTip(self.session.undo_label);self.redo.setToolTip(self.session.redo_label)

    def _restore_original(self) -> None:
        names=NameRecord.parse(self.session.original_asset(AssetType.LEVEL_NAMES,self.current)).values
        self._loading=True
        for key,line in self.fields.items():line.setText(getattr(names,key))
        self._loading=False;self._edited()

    def _reset_course(self) -> None:
        self.drafts.pop(self.current,None);self._load_fields()
        item=self.list.currentItem()
        if item is not None:item.setText(1,self.session._catalog.levels[self.current].name)
        self._invalidate()

    def build_preview(self) -> None:
        self.plan=None;self.apply.setEnabled(False)
        try:
            plan=plan_names(self.session,self.drafts)
            self.plan=plan;self.budget.setPlainText(plan.report.to_text())
            self.message.setStyleSheet('color: #fbbf24;' if plan.warnings else '')
            self.message.setText(f'{len(plan.after)} course(s) ready. Name block in game RAM: {plan.ram_before:,} → {plan.ram_after:,} bytes ({plan.ram_after-plan.ram_before:+,}). '
                'Apply is one project undo step.\n'+'\n'.join(plan.warnings))
            self.apply.setEnabled(bool(plan.after))
        except (ValueError,OSError) as error:
            self.message.setText(f'Name preview rejected: {error}');self.message.setStyleSheet('color: #fca5a5;')

    def _apply(self) -> None:
        if self.plan is None:return
        try:
            self.session.apply_course_names(self.plan)
            self.drafts.clear();self.reload();self.names_changed.emit()
            self.message.setText('Course names applied. Save the project or export your ROM.')
        except ValueError as error:
            self.message.setText(f'Apply rejected: {error}');self.apply.setEnabled(False)

    def _history(self,redo: bool) -> None:
        if self.drafts:return
        self.history_requested.emit(redo);self.reload()
