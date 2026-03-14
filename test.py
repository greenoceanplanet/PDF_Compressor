import fitz
import inspect

doc = fitz.open()
page = doc.new_page()
pix = page.get_pixmap()

try:
    print(pix.tobytes("jpeg", quality=50))
    print("SUCCESS quality")
except Exception as e:
    print("ERROR quality:", str(e))
