import sys
import os
import fitz  # PyMuPDF
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QSlider, QProgressBar, QMessageBox, QGroupBox,
                             QScrollArea, QCheckBox, QLineEdit, QSpinBox, QComboBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QByteArray, QBuffer
from PyQt6.QtGui import QPixmap, QImage, QIntValidator

class DraggableLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.is_dragging = False
        self.last_pos = None
        self.zoom_mode = False
        self.scroll_area = None

    def mousePressEvent(self, event):
        if self.zoom_mode and event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.last_pos = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.zoom_mode and self.is_dragging:
            curr_pos = event.globalPosition().toPoint()
            delta = curr_pos - self.last_pos
            self.last_pos = curr_pos
            if self.scroll_area:
                h_bar = self.scroll_area.horizontalScrollBar()
                h_bar.setValue(h_bar.value() - delta.x())
                v_bar = self.scroll_area.verticalScrollBar()
                v_bar.setValue(v_bar.value() - delta.y())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            if self.zoom_mode:
                self.setCursor(Qt.CursorShape.OpenHandCursor)

class CompressorThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, int)
    error = pyqtSignal(str)

    def __init__(self, input_path, output_path, dpi, quality):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.dpi = dpi
        self.quality = quality

    def run(self):
        try:
            doc = fitz.open(self.input_path)
            new_doc = fitz.open()
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Render page to an image
                pix = page.get_pixmap(dpi=self.dpi)
                # Convert to JPEG with specified quality using QImage
                fmt = QImage.Format.Format_RGBA8888 if pix.alpha else QImage.Format.Format_RGB888
                image = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
                
                byte_array = QByteArray()
                buffer = QBuffer(byte_array)
                buffer.open(QBuffer.OpenModeFlag.WriteOnly)
                image.save(buffer, "JPEG", quality=self.quality)
                img_data = byte_array.data()
                
                # Create a new page with the same dimensions
                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                # Insert the compressed image covering the whole page
                new_page.insert_image(page.rect, stream=img_data)
                
                self.progress.emit(int((page_num + 1) / len(doc) * 100))
                
            new_doc.save(self.output_path)
            new_doc.close()
            doc.close()
            
            final_size = os.path.getsize(self.output_path)
            self.finished.emit(self.output_path, final_size)
        except Exception as e:
            self.error.emit(str(e))


class PDFCompressorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 그림 압축기 (PDF Compressor)")
        self.resize(1000, 700)
        self.setMinimumSize(800, 600)
        
        self.input_path = None
        self.doc = None
        self.current_preview_page = 0
        self.zoom_1_1 = False
        
        self.init_ui()
        
        # Debounce timer for preview updates to avoid lag when dragging sliders
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_preview)
        
    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)
        
        # --- Left Panel (Controls) ---
        control_layout = QVBoxLayout()
        
        # 1. Load File Button
        self.btn_load = QPushButton("1. PDF 파일 불러오기")
        self.btn_load.clicked.connect(self.load_file)
        self.btn_load.setMinimumHeight(50)
        self.btn_load.setStyleSheet("font-size: 14pt; font-weight: bold;")
        control_layout.addWidget(self.btn_load)
        
        # 2. File Status
        self.lbl_status = QLabel("파일을 불러와주세요.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size: 11pt; color: #333; margin-top: 10px;")
        control_layout.addWidget(self.lbl_status)
        
        self.lbl_size = QLabel("현재 크기: -")
        self.lbl_size.setStyleSheet("font-size: 11pt;")
        control_layout.addWidget(self.lbl_size)
        
        control_layout.addSpacing(20)
        
        # 3. Quality Setting (JPEG Compression Rate)
        quality_group = QGroupBox("3. 압축률 설정 (Quality)")
        quality_layout = QVBoxLayout()
        self.lbl_quality = QLabel("품질 (작을수록 용량 감소):")
        
        q_control_layout = QHBoxLayout()
        self.slider_quality = QSlider(Qt.Orientation.Horizontal)
        self.slider_quality.setRange(10, 100)
        self.slider_quality.setValue(70)
        
        self.spin_quality = QSpinBox()
        self.spin_quality.setRange(10, 100)
        self.spin_quality.setValue(70)
        
        self.slider_quality.valueChanged.connect(self.spin_quality.setValue)
        self.spin_quality.valueChanged.connect(self.slider_quality.setValue)
        self.slider_quality.valueChanged.connect(self.on_slider_changed)
        
        q_control_layout.addWidget(self.slider_quality)
        q_control_layout.addWidget(self.spin_quality)
        
        quality_layout.addWidget(self.lbl_quality)
        quality_layout.addLayout(q_control_layout)
        quality_group.setLayout(quality_layout)
        control_layout.addWidget(quality_group)
        
        # 4. DPI Setting (Image Resolution)
        dpi_group = QGroupBox("4. 이미지 해상도 설정 (DPI)")
        dpi_layout = QVBoxLayout()
        self.lbl_dpi = QLabel("DPI (작을수록 용량 감소):")
        
        dpi_control_layout = QHBoxLayout()
        self.slider_dpi = QSlider(Qt.Orientation.Horizontal)
        self.slider_dpi.setRange(72, 300)
        self.slider_dpi.setValue(150)
        
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(72, 300)
        self.spin_dpi.setValue(150)
        
        self.slider_dpi.valueChanged.connect(self.spin_dpi.setValue)
        self.spin_dpi.valueChanged.connect(self.slider_dpi.setValue)
        self.slider_dpi.valueChanged.connect(self.on_slider_changed)
        
        dpi_control_layout.addWidget(self.slider_dpi)
        dpi_control_layout.addWidget(self.spin_dpi)
        
        dpi_layout.addWidget(self.lbl_dpi)
        dpi_layout.addLayout(dpi_control_layout)
        dpi_group.setLayout(dpi_layout)
        control_layout.addWidget(dpi_group)
        
        control_layout.addSpacing(20)
        
        # 5. Estimated Size
        self.lbl_est_size = QLabel("예상 크기: -")
        self.lbl_est_size.setStyleSheet("font-size: 12pt; font-weight: bold; color: #0055ff;")
        control_layout.addWidget(self.lbl_est_size)
        
        control_layout.addStretch()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        control_layout.addWidget(self.progress_bar)
        
        self.btn_compress = QPushButton("압축 저장하기")
        self.btn_compress.clicked.connect(self.compress_file)
        self.btn_compress.setMinimumHeight(60)
        self.btn_compress.setEnabled(False)
        self.btn_compress.setStyleSheet("font-size: 14pt; font-weight: bold; background-color: #4CAF50; color: white;")
        control_layout.addWidget(self.btn_compress)
        
        layout.addLayout(control_layout, 1)
        
        # --- Right Panel (Preview) ---
        preview_group = QGroupBox("6. 처리 전/후 비교")
        preview_layout = QVBoxLayout()
        
        comparison_layout = QHBoxLayout()
        
        # Original (Left)
        orig_layout = QVBoxLayout()
        orig_label = QLabel("원본 (해상도 유지 & 크기만 동기화)")
        orig_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        orig_label.setStyleSheet("font-weight: bold; padding: 5px;")
        orig_layout.addWidget(orig_label)
        
        self.scroll_area_orig = QScrollArea()
        self.scroll_area_orig.setWidgetResizable(True)
        self.lbl_preview_orig = DraggableLabel("PDF를 불러오면 원본이 표시됩니다.")
        self.lbl_preview_orig.scroll_area = self.scroll_area_orig
        self.lbl_preview_orig.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview_orig.setStyleSheet("background-color: #e0e0e0;")
        self.scroll_area_orig.setWidget(self.lbl_preview_orig)
        orig_layout.addWidget(self.scroll_area_orig)
        
        # Compressed (Right)
        comp_layout = QVBoxLayout()
        comp_label = QLabel("압축 후 (현재 설정 적용)")
        comp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        comp_label.setStyleSheet("font-weight: bold; padding: 5px; color: #0055ff;")
        comp_layout.addWidget(comp_label)
        
        self.scroll_area_comp = QScrollArea()
        self.scroll_area_comp.setWidgetResizable(True)
        self.lbl_preview_comp = DraggableLabel("여기에 압축 미리보기가 표시됩니다.")
        self.lbl_preview_comp.scroll_area = self.scroll_area_comp
        self.lbl_preview_comp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview_comp.setStyleSheet("background-color: #e0e0e0;")
        self.scroll_area_comp.setWidget(self.lbl_preview_comp)
        comp_layout.addWidget(self.scroll_area_comp)
        
        comparison_layout.addLayout(orig_layout)
        comparison_layout.addLayout(comp_layout)
        preview_layout.addLayout(comparison_layout, 1)
        
        # Sync scrollbars
        self.scroll_area_orig.horizontalScrollBar().valueChanged.connect(self.scroll_area_comp.horizontalScrollBar().setValue)
        self.scroll_area_comp.horizontalScrollBar().valueChanged.connect(self.scroll_area_orig.horizontalScrollBar().setValue)
        self.scroll_area_orig.verticalScrollBar().valueChanged.connect(self.scroll_area_comp.verticalScrollBar().setValue)
        self.scroll_area_comp.verticalScrollBar().valueChanged.connect(self.scroll_area_orig.verticalScrollBar().setValue)

        # Controls under preview
        bottom_controls_layout = QHBoxLayout()
        
        # ComboBox for view modes
        bottom_controls_layout.addWidget(QLabel("보기 모드:"))
        self.cbo_zoom = QComboBox()
        self.cbo_zoom.addItems(["화면 전체 맞추기", "가로 폭 맞추기", "세로 높이 맞추기", "1:1 실제 크기"])
        self.cbo_zoom.currentIndexChanged.connect(self.on_zoom_changed)
        self.zoom_mode = 0  # 0: Fit Screen, 1: Fit Width, 2: Fit Height, 3: 1:1
        bottom_controls_layout.addWidget(self.cbo_zoom)
        bottom_controls_layout.addSpacing(20)

        # Pagination controls
        page_nav_layout = QHBoxLayout()
        self.btn_prev_page = QPushButton("◀ 이전")
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.btn_prev_page.setEnabled(False)
        
        self.edit_page = QLineEdit("0")
        self.edit_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_page.setFixedWidth(40)
        self.edit_page.setValidator(QIntValidator(1, 9999))
        self.edit_page.returnPressed.connect(self.jump_to_page)
        
        self.lbl_total_pages = QLabel("/ 0")
        
        self.btn_next_page = QPushButton("다음 ▶")
        self.btn_next_page.clicked.connect(self.next_page)
        self.btn_next_page.setEnabled(False)

        page_nav_layout.addWidget(self.btn_prev_page)
        page_nav_layout.addWidget(self.edit_page)
        page_nav_layout.addWidget(self.lbl_total_pages)
        page_nav_layout.addWidget(self.btn_next_page)
        
        bottom_controls_layout.addStretch()
        bottom_controls_layout.addLayout(page_nav_layout)
        
        preview_layout.addLayout(bottom_controls_layout)
        preview_group.setLayout(preview_layout)
        
        layout.addWidget(preview_group, 2)
        
    def load_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "PDF 파일 선택", "", "PDF Files (*.pdf)")
        if file_name:
            self.input_path = file_name
            self.lbl_status.setText(f"불러옴: {os.path.basename(file_name)}")
            
            size_mb = os.path.getsize(file_name) / (1024 * 1024)
            self.lbl_size.setText(f"현재 크기: {size_mb:.2f} MB")
            
            if self.doc:
                self.doc.close()
            # Open the document initially to get pages
            self.doc = fitz.open(file_name)
            self.current_preview_page = 0
            
            self.btn_compress.setEnabled(True)
            self.update_nav_buttons()
            self.on_slider_changed() # Trigger preview update

    def update_nav_buttons(self):
        if not self.doc:
            return
        total_pages = len(self.doc)
        
        self.edit_page.setText(str(self.current_preview_page + 1))
        self.lbl_total_pages.setText(f"/ {total_pages}")
        
        self.btn_prev_page.setEnabled(self.current_preview_page > 0)
        self.btn_next_page.setEnabled(self.current_preview_page < total_pages - 1)

    def jump_to_page(self):
        if not self.doc:
            return
        
        try:
            target_page = int(self.edit_page.text()) - 1
            total_pages = len(self.doc)
            
            if target_page < 0:
                target_page = 0
            elif target_page >= total_pages:
                target_page = total_pages - 1
                
            self.current_preview_page = target_page
            self.update_nav_buttons()
            self.preview_timer.start(100)
        except ValueError:
            self.update_nav_buttons()
            
    def update_estimated_size(self):
        if not self.input_path or not self.doc:
            return
            
        dpi = self.slider_dpi.value()
        quality = self.slider_quality.value()
        
        try:
            # 예상 크기 다듬기: 초반 최대 5개 페이지를 샘플링하여 평균 크기를 구한 뒤
            # 전체 페이지 수를 곱해 더 정확한 예상 용량을 고정 계산.
            sample_count = min(5, len(self.doc))
            total_sample_bytes = 0
            
            for i in range(sample_count):
                page = self.doc[i]
                pix = page.get_pixmap(dpi=dpi)
                
                fmt = QImage.Format.Format_RGBA8888 if pix.alpha else QImage.Format.Format_RGB888
                image = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
                
                byte_array = QByteArray()
                buffer = QBuffer(byte_array)
                buffer.open(QBuffer.OpenModeFlag.WriteOnly)
                image.save(buffer, "JPEG", quality=quality)
                total_sample_bytes += byte_array.size()
            
            # 평균 1페이지 평균 용량 * 총 페이지 수
            avg_size_bytes = total_sample_bytes / sample_count
            est_size_bytes = avg_size_bytes * len(self.doc)
            est_size_mb = est_size_bytes / (1024 * 1024)
            
            self.lbl_est_size.setText(f"예상 크기: 약 {est_size_mb:.2f} MB")
        except Exception:
            self.lbl_est_size.setText("예상 크기: 오류")

    def prev_page(self):
        if self.current_preview_page > 0:
            self.current_preview_page -= 1
            self.update_nav_buttons()
            self.preview_timer.start(100)

    def next_page(self):
        if self.doc and self.current_preview_page < len(self.doc) - 1:
            self.current_preview_page += 1
            self.update_nav_buttons()
            self.preview_timer.start(100)
            
    def on_slider_changed(self):
        if self.input_path and self.doc:
            self.lbl_est_size.setText("예상 크기 계산 중...")
            # Wait a bit before rendering to avoid lag during slider drag
            self.preview_timer.start(400) 
            
    def on_zoom_changed(self, index):
        self.zoom_mode = index
        is_draggable = (index != 0)
        self.lbl_preview_orig.zoom_mode = is_draggable
        self.lbl_preview_comp.zoom_mode = is_draggable
        
        if is_draggable:
            self.lbl_preview_orig.setCursor(Qt.CursorShape.OpenHandCursor)
            self.lbl_preview_comp.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.lbl_preview_orig.unsetCursor()
            self.lbl_preview_comp.unsetCursor()
            
        if self.input_path and self.doc:
            self.preview_timer.start(100)
            
    def update_preview(self):
        if not self.input_path or not self.doc:
            return
            
        dpi = self.slider_dpi.value()
        quality = self.slider_quality.value()
        
        try:
            # 1. 렌더링 후 이미지 데이터 추출 (압축용)
            page = self.doc[self.current_preview_page]
            pix_comp = page.get_pixmap(dpi=dpi)
            
            fmt_comp = QImage.Format.Format_RGBA8888 if pix_comp.alpha else QImage.Format.Format_RGB888
            image_comp = QImage(pix_comp.samples, pix_comp.width, pix_comp.height, pix_comp.stride, fmt_comp)
            
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QBuffer.OpenModeFlag.WriteOnly)
            image_comp.save(buffer, "JPEG", quality=quality)
            img_data = byte_array.data()
            
            # 예상 사이즈는 별도 함수로 호출하여 페이지를 넘겨도 들쭉날쭉 변하지 않도록 고정
            self.update_estimated_size()
            
            # 2. 원본 이미지 렌더링 (비교용, 선명도 유지를 위해 150 DPI 고정 렌더링)
            pix_orig = page.get_pixmap(dpi=150)
            fmt_orig = QImage.Format.Format_RGBA8888 if pix_orig.alpha else QImage.Format.Format_RGB888
            image_orig = QImage(pix_orig.samples, pix_orig.width, pix_orig.height, pix_orig.stride, fmt_orig)
            pixmap_orig = QPixmap.fromImage(image_orig)
            
            # 3. 화면에 미리보기 업데이트
            image_comp_reloaded = QImage.fromData(img_data)
            pixmap_comp = QPixmap.fromImage(image_comp_reloaded)
            
            if self.zoom_mode == 3: # 1:1
                # 1:1 모드일 때 원본(150 DPI)을 압축본(현재 슬라이더 DPI)의 해상도 껍데기(모니터 상 크기)에 강제로 맞춰서 선명도만 유지
                scaled_orig = pixmap_orig.scaled(pixmap_comp.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                scaled_comp = pixmap_comp
            elif self.zoom_mode == 1: # 가로 폭 맞추기
                vp_w_orig = self.scroll_area_orig.viewport().width()
                scaled_orig = pixmap_orig.scaledToWidth(vp_w_orig, Qt.TransformationMode.SmoothTransformation)
                vp_w_comp = self.scroll_area_comp.viewport().width()
                scaled_comp = pixmap_comp.scaledToWidth(vp_w_comp, Qt.TransformationMode.SmoothTransformation)
            elif self.zoom_mode == 2: # 세로 높이 맞추기
                vp_h_orig = self.scroll_area_orig.viewport().height()
                scaled_orig = pixmap_orig.scaledToHeight(vp_h_orig, Qt.TransformationMode.SmoothTransformation)
                vp_h_comp = self.scroll_area_comp.viewport().height()
                scaled_comp = pixmap_comp.scaledToHeight(vp_h_comp, Qt.TransformationMode.SmoothTransformation)
            else: # 화면 전체 맞추기
                vp_size_orig = self.scroll_area_orig.viewport().size()
                scaled_orig = pixmap_orig.scaled(vp_size_orig, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                vp_size_comp = self.scroll_area_comp.viewport().size()
                scaled_comp = pixmap_comp.scaled(vp_size_comp, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            self.lbl_preview_orig.setPixmap(scaled_orig)
            self.lbl_preview_comp.setPixmap(scaled_comp)
            
            if self.zoom_mode != 0:
                self.lbl_preview_orig.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                self.lbl_preview_comp.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            else:
                self.lbl_preview_orig.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lbl_preview_comp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
        except Exception as e:
            self.lbl_preview_orig.setText(f"미리보기 생성 오류 (원본): {str(e)}")
            self.lbl_preview_comp.setText(f"미리보기 생성 오류 (압축): {str(e)}")
            
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 윈도우 크기가 변할 때 미리보기 이미지 크기도 다시 맞춤
        if self.input_path and self.doc:
            self.preview_timer.start(200)
            
    def compress_file(self):
        if not self.input_path:
            return
            
        # 기본 저장 파일명 제안
        default_out = self.input_path.rsplit('.', 1)[0] + "_compressed.pdf"
        output_path, _ = QFileDialog.getSaveFileName(self, "압축 파일 저장", default_out, "PDF Files (*.pdf)")
        
        if not output_path:
            return
            
        # UI 비활성화
        self.btn_compress.setEnabled(False)
        self.btn_load.setEnabled(False)
        self.slider_dpi.setEnabled(False)
        self.slider_quality.setEnabled(False)
        self.progress_bar.setValue(0)
        
        dpi = self.slider_dpi.value()
        quality = self.slider_quality.value()
        
        # 백그라운드 스레드에서 시작
        self.thread = CompressorThread(self.input_path, output_path, dpi, quality)
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.finished.connect(self.on_compress_finished)
        self.thread.error.connect(self.on_compress_error)
        self.thread.start()
        
    def on_compress_finished(self, out_path, size_bytes):
        # UI 다시 활성화
        self.btn_compress.setEnabled(True)
        self.btn_load.setEnabled(True)
        self.slider_dpi.setEnabled(True)
        self.slider_quality.setEnabled(True)
        self.progress_bar.setValue(100)
        
        size_mb = size_bytes / (1024 * 1024)
        QMessageBox.information(self, "압축 완료", f"압축이 성공적으로 완료되었습니다!\n\n저장 경로: {out_path}\n최종 크기: {size_mb:.2f} MB")
        
    def on_compress_error(self, err):
        # UI 다시 활성화
        self.btn_compress.setEnabled(True)
        self.btn_load.setEnabled(True)
        self.slider_dpi.setEnabled(True)
        self.slider_quality.setEnabled(True)
        QMessageBox.critical(self, "오류 발생", f"문서 압축 중 오류가 발생했습니다:\n{err}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 윈도우 스타일 (약간 깔끔하게)
    app.setStyle("Fusion")
    
    window = PDFCompressorApp()
    window.show()
    sys.exit(app.exec())
