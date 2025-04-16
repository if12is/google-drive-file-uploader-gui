import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import pickle
import threading # لاستخدام مؤشر التقدم دون تجميد الواجهة
import queue # لاستخدام طريقة أكثر أمانًا لتحديث الواجهة من thread
# Add import for clipboard functionality
import pyperclip

# مكتبات Google Drive API
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# --- إعدادات Google Drive API ---
# (نفس إرشادات الإعداد السابقة)
# 1. انتقل إلى Google Cloud Console: https://console.cloud.google.com/
# 2. أنشئ مشروعًا جديدًا أو استخدم مشروعًا قائمًا.
# 3. انتقل إلى "APIs & Services" -> "Library".
# 4. ابحث عن "Google Drive API" وقم بتمكينه (Enable).
# 5. انتقل إلى "APIs & Services" -> "Credentials".
# 6. انقر على "Create Credentials" -> "OAuth client ID".
# 7. قم بتكوين شاشة الموافقة (OAuth consent screen). اختر "External" وأضف نطاق ".../auth/drive.file". أضف بريدك الإلكتروني كـ "Test user" إذا كانت الحالة "Testing".
# 8. اختر "Desktop app" كنوع للتطبيق.
# 9. انقر على "Create".
# 10. قم بتنزيل ملف JSON -> أعد تسميته إلى "client_secrets.json" وضعه في نفس مجلد السكربت.

SCOPES = ['https://www.googleapis.com/auth/drive.file']
CLIENT_SECRETS_FILE = 'client_secrets.json'
TOKEN_PICKLE_FILE = 'token.pickle'

# --- وظائف Google Drive ---

def get_drive_service(status_callback_queue):
    """يقوم بمصادقة المستخدم والحصول على كائن خدمة Drive API."""
    creds = None
    if os.path.exists(TOKEN_PICKLE_FILE):
        with open(TOKEN_PICKLE_FILE, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                # استخدام الطابور لإرسال رسالة الخطأ إلى الواجهة
                status_callback_queue.put(f"خطأ في المصادقة: فشل تحديث التوكن: {e}\nيرجى حذف ملف 'token.pickle' والمحاولة مرة أخرى.")
                if os.path.exists(TOKEN_PICKLE_FILE):
                    os.remove(TOKEN_PICKLE_FILE)
                return None
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                 status_callback_queue.put(f"خطأ في الإعداد: لم يتم العثور على ملف '{CLIENT_SECRETS_FILE}'.")
                 return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
                status_callback_queue.put("سيتم فتح المتصفح للمصادقة...")
                creds = flow.run_local_server(port=0)
                status_callback_queue.put("اكتملت المصادقة الأولية.")
            except Exception as e:
                 status_callback_queue.put(f"خطأ في المصادقة: فشل تدفق المصادقة: {e}")
                 return None

        with open(TOKEN_PICKLE_FILE, 'wb') as token:
            pickle.dump(creds, token)

    try:
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        status_callback_queue.put(f"خطأ في بناء الخدمة: فشل في بناء خدمة Drive: {e}")
        return None


def upload_file_to_drive(service, file_path, drive_filename, visibility, progress_callback_queue, status_callback_queue):
    """يرفع ملفًا إلى Google Drive ويرسل التحديثات عبر الطوابير.
    بعد الرفع، يتحقق من وجود الملف فعليًا على Google Drive ويعيد الرابط أو رسالة خطأ."""
    if not service:
        status_callback_queue.put("خطأ: خدمة Drive غير متاحة.")
        return

    if not os.path.exists(file_path):
        status_callback_queue.put(f"خطأ: الملف '{file_path}' غير موجود.")
        return

    try:
        file_metadata = {'name': drive_filename}
        status_callback_queue.put(f"بدء رفع الملف: {drive_filename}...")
        media = MediaFileUpload(file_path, resumable=True)
        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        )

        response = None
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    progress_callback_queue.put(progress)
                    status_callback_queue.put(f"جاري الرفع... {progress}%")
            except Exception as e:
                status_callback_queue.put(f"خطأ أثناء الرفع (next_chunk): {e}")
                progress_callback_queue.put(0)
                return

        # تحقق من رفع الملف فعليًا عبر محاولة جلبه من Google Drive
        file_id = response.get('id')
        file_link = response.get('webViewLink')
        progress_callback_queue.put(100)
        status_callback_queue.put(f"اكتمل الرفع بنجاح! معرف الملف: {file_id}")

        # تحقق من وجود الملف على Google Drive
        try:
            check = service.files().get(fileId=file_id, fields='id, webViewLink').execute()
            # إذا نجح الاستدعاء، الملف موجود
            found_link = check.get('webViewLink')
            status_callback_queue.put(f"LINK:{found_link}")
            status_callback_queue.put(f"تم التحقق من وجود الملف على Google Drive.")
        except Exception as e:
            status_callback_queue.put(f"خطأ: لم يتم العثور على الملف بعد الرفع. {e}")
            status_callback_queue.put("لم يتم رفع الملف بنجاح. يرجى المحاولة مرة أخرى.")
            return

        # التعامل مع خيار "عام" (قابل للمشاركة بالرابط)
        if visibility == 'public':
            status_callback_queue.put("جاري محاولة جعل الملف قابلاً للمشاركة...")
            try:
                permission = {
                    'type': 'anyone',
                    'role': 'reader'
                }
                service.permissions().create(fileId=file_id, body=permission).execute()
                updated_file = service.files().get(fileId=file_id, fields='webViewLink').execute()
                shareable_link = updated_file.get('webViewLink')
                status_callback_queue.put("تم جعل الملف قابلاً للمشاركة بنجاح (أي شخص لديه الرابط يمكنه العرض).")
                status_callback_queue.put(f"PUBLIC_LINK:{shareable_link}")
                status_callback_queue.put(f"رابط المشاركة العام: {shareable_link}")
            except Exception as e:
                status_callback_queue.put(f"خطأ أثناء محاولة جعل الملف قابلاً للمشاركة: {e}")
                status_callback_queue.put("بقي الملف خاصًا. يمكنك تغيير الأذونات يدويًا في Google Drive.")
        else:
            status_callback_queue.put("تم رفع الملف كملف خاص.")

    except Exception as e:
        status_callback_queue.put(f"حدث خطأ أثناء الرفع: {e}")
        progress_callback_queue.put(0)


# --- واجهة المستخدم الرسومية (GUI) ---

class DriveUploaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("أداة رفع ملفات Google Drive")
        self.root.geometry("550x450")

        # إنشاء طوابير للتواصل بين الـ thread والواجهة
        self.progress_queue = queue.Queue()
        self.status_queue = queue.Queue()

        content_frame = ttk.Frame(root, padding="20 20 20 20")
        content_frame.pack(expand=True, fill=tk.BOTH)

        # --- اختيار الملف ---
        file_frame = ttk.LabelFrame(content_frame, text="اختيار الملف", padding="10 10 10 10")
        file_frame.pack(fill=tk.X, pady=10)
        self.file_path_var = tk.StringVar()
        self.file_label = ttk.Label(file_frame, text="لم يتم اختيار ملف")
        self.file_label.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        self.browse_button = ttk.Button(file_frame, text="تصفح...", command=self.select_file)
        self.browse_button.pack(side=tk.RIGHT, padx=5)

        # --- خيارات الرفع ---
        options_frame = ttk.LabelFrame(content_frame, text="خيارات الرفع", padding="10 10 10 10")
        options_frame.pack(fill=tk.X, pady=10)
        ttk.Label(options_frame, text="اسم الملف على Drive:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.drive_filename_var = tk.StringVar()
        self.drive_filename_entry = ttk.Entry(options_frame, textvariable=self.drive_filename_var, width=40)
        self.drive_filename_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        ttk.Label(options_frame, text="مستوى الرؤية:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.visibility_var = tk.StringVar(value='private')
        private_rb = ttk.Radiobutton(options_frame, text="خاص (افتراضي)", variable=self.visibility_var, value='private')
        public_rb = ttk.Radiobutton(options_frame, text="عام (قابل للمشاركة بالرابط)", variable=self.visibility_var, value='public')
        private_rb.grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        public_rb.grid(row=2, column=1, padx=5, pady=2, sticky=tk.W)
        options_frame.columnconfigure(1, weight=1)

        # --- زر الرفع ---
        self.upload_button = ttk.Button(content_frame, text="بدء الرفع إلى Drive", command=self.start_upload_thread)
        self.upload_button.pack(pady=15)

        # --- شريط التقدم ---
        progress_frame = ttk.LabelFrame(content_frame, text="التقدم", padding="10 10 10 10")
        progress_frame.pack(fill=tk.X, pady=10)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, expand=True)

        # --- منطقة عرض الحالة والأخطاء ---
        status_frame = ttk.LabelFrame(content_frame, text="الحالة / الأخطاء", padding="10 10 10 10")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.status_text = tk.Text(status_frame, height=6, wrap=tk.WORD, state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.status_text.yview)
        self.status_text.config(yscrollcommand=scrollbar.set)
        self.status_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Add a labeled frame for the link display and copy functionality
        link_frame = ttk.LabelFrame(content_frame, text="رابط الملف", padding="10 10 10 10")
        link_frame.pack(fill=tk.X, pady=10, before=status_frame)
        
        # A read-only entry field to display the current link
        self.link_var = tk.StringVar()
        self.link_entry = ttk.Entry(link_frame, textvariable=self.link_var, width=60, state="readonly")
        self.link_entry.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # Copy button next to the entry field
        self.copy_link_button = ttk.Button(link_frame, text="نسخ الرابط", 
                                          command=self.copy_link_to_clipboard, state=tk.DISABLED)
        self.copy_link_button.pack(side=tk.RIGHT, padx=5)

        # Add variable to store the shareable link
        self.current_shareable_link = None

        # --- متغيرات الحالة ---
        self.service = None
        self.upload_thread = None

        # بدء مراقبة الطوابير لتحديث الواجهة
        self.check_queues()

    def select_file(self):
        """يفتح مربع حوار لاختيار ملف."""
        filepath = filedialog.askopenfilename()
        if filepath:
            self.file_path_var.set(filepath)
            filename = os.path.basename(filepath)
            self.file_label.config(text=filename)
            if not self.drive_filename_var.get():
                self.drive_filename_var.set(filename)
            self._log_status_ui(f"تم اختيار الملف: {filepath}") # تحديث مباشر للواجهة
        else:
            self._log_status_ui("تم إلغاء اختيار الملف.") # تحديث مباشر للواجهة

    def _log_status_ui(self, message):
        """(تعمل في الـ thread الرئيسي) تحدث منطقة الحالة."""
        self.status_text.config(state=tk.NORMAL)
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)

    def _update_progress_ui(self, value):
        """(تعمل في الـ thread الرئيسي) تحدث شريط التقدم."""
        self.progress_var.set(value)

    def check_queues(self):
        """تفحص الطوابير بشكل دوري لتحديث الواجهة."""
        try:
            link_to_show = None
            while not self.status_queue.empty():
                message = self.status_queue.get_nowait()

                # Prefer public link if available
                if message.startswith("PUBLIC_LINK:"):
                    link = message[12:]
                    link_to_show = link
                    self.current_shareable_link = link
                    continue
                elif message.startswith("LINK:"):
                    link = message[5:]
                    # Only set if no public link has been set in this batch
                    if not link_to_show:
                        link_to_show = link
                        self.current_shareable_link = link
                    continue

                # If upload failed, clear the link field
                if "لم يتم رفع الملف بنجاح" in message or "خطأ أثناء الرفع" in message:
                    link_to_show = ""
                    self.current_shareable_link = None

                if message == "UPLOAD_COMPLETE_ENABLE_BUTTONS":
                    self.enable_buttons()
                else:
                    self._log_status_ui(message)

            # Always update the link field at the end of queue processing
            if link_to_show is not None:
                self.link_var.set(link_to_show)
                self.copy_link_button.config(state=tk.NORMAL if link_to_show else tk.DISABLED)

            while not self.progress_queue.empty():
                progress = self.progress_queue.get_nowait()
                self._update_progress_ui(progress)

            self.root.after(100, self.check_queues)

        except queue.Empty:
            self.root.after(100, self.check_queues)

    def copy_link_to_clipboard(self):
        """ينسخ رابط المشاركة إلى الحافظة"""
        if self.current_shareable_link:
            pyperclip.copy(self.current_shareable_link)
            self._log_status_ui("تم نسخ الرابط إلى الحافظة.")
            
            # Provide visual feedback that the copy was successful
            original_text = self.copy_link_button["text"]
            self.copy_link_button["text"] = "✓ تم النسخ"
            self.root.after(1500, lambda: self.copy_link_button.config(text=original_text))
        else:
            self._log_status_ui("لا يوجد رابط متاح للنسخ.")

    def start_upload_thread(self):
        """يبدأ عملية الرفع في thread منفصل."""
        local_file_path = self.file_path_var.get()
        drive_filename = self.drive_filename_var.get()
        visibility = self.visibility_var.get()

        if not local_file_path:
            messagebox.showwarning("تنبيه", "يرجى اختيار ملف أولاً.")
            return
        if not drive_filename:
            messagebox.showwarning("تنبيه", "يرجى إدخال اسم للملف على Google Drive.")
            return

        self.browse_button.config(state=tk.DISABLED)
        self.upload_button.config(state=tk.DISABLED)
        self._update_progress_ui(0) # إعادة تعيين شريط التقدم
        self._log_status_ui("جاري المصادقة مع Google Drive...") # تحديث مباشر

        # Clear link display and disable copy button
        self.link_var.set("")
        self.copy_link_button.config(state=tk.DISABLED)
        self.current_shareable_link = None

        # مسح الطوابير قبل البدء
        while not self.status_queue.empty(): self.status_queue.get_nowait()
        while not self.progress_queue.empty(): self.progress_queue.get_nowait()

        self.upload_thread = threading.Thread(
            target=self.authenticate_and_upload,
            args=(local_file_path, drive_filename, visibility),
            daemon=True
        )
        self.upload_thread.start()

    def authenticate_and_upload(self, local_file_path, drive_filename, visibility):
        """يقوم بالمصادقة ثم الرفع (يعمل في thread منفصل)."""
        try:
            # Reset the shareable link at the start of a new upload
            self.current_shareable_link = None
            
            # تمرير طابور الحالة لدالة المصادقة
            self.service = get_drive_service(self.status_queue)

            if self.service:
                self.status_queue.put("تمت المصادقة بنجاح.")
                upload_file_to_drive(
                    self.service,
                    local_file_path,
                    drive_filename,
                    visibility,
                    self.progress_queue, # تمرير طابور التقدم
                    self.status_queue     # تمرير طابور الحالة
                )
            else:
                self.status_queue.put("فشلت عملية المصادقة أو تم إلغاؤها.")
                self.progress_queue.put(0)

        except Exception as e:
            self.status_queue.put(f"حدث خطأ غير متوقع في thread الرفع: {e}")
            self.progress_queue.put(0)

        finally:
            # إرسال إشارة لإعادة تمكين الأزرار عبر الطابور
            self.status_queue.put("UPLOAD_COMPLETE_ENABLE_BUTTONS")

    def enable_buttons(self):
        """(تعمل في الـ thread الرئيسي) تعيد تمكين الأزرار."""
        self.browse_button.config(state=tk.NORMAL)
        self.upload_button.config(state=tk.NORMAL)
        # Note: We don't enable the copy link button here - it's enabled when a link is available


# --- تشغيل التطبيق ---
if __name__ == "__main__":
    root = tk.Tk()
    app = DriveUploaderApp(root)
    root.mainloop()
