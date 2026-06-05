# 🎙️ CapCut TTS API Client (Bilingual: VI / EN)

> **🇻🇳 Việt Nam:** Dự án mã nguồn mở cung cấp giải pháp chuyển đổi văn bản thành giọng nói (TTS) thông qua kết nối trực tiếp tới API ẩn của CapCut Desktop mà không cần giao diện người dùng. Hỗ trợ đầy đủ macOS và Windows.
>
> **🇬🇧 English:** A high-performance Python/C++ wrapper connecting directly to CapCut Desktop's internal APIs for Text-to-Speech (TTS) synthesis without spawning a GUI. Fully compatible with both macOS and Windows.

---

## 🗺️ 1. File Structure & Roles / Cấu Trúc File & Chức Năng

Here is the breakdown of the project layout and the function of each file:
Dưới đây là chi tiết sơ đồ thư mục và vai trò cụ thể của từng tệp tin:

### 🍏 macOS Component (`capcut_macos/`)
*   **[capcut_macos/capcut_tts_ctypes.py](file:///Users/admin/Downloads/capcut_new/capcut_macos/capcut_tts_ctypes.py)**
    *   🇻🇳 Kịch bản Python chính cho macOS. Chịu trách nhiệm khởi tạo payload SSML, ký mã hóa (signing) bằng RSA, gọi thực thi binary `cronet_helper` để gửi yêu cầu và thực hiện polling tải audio.
    *   🇬🇧 The main Python orchestrator for macOS. Formulates the SSML payload, generates the RSA signature, triggers the `cronet_helper` binary, and polls the server for completion.
*   **[capcut_macos/config.py](file:///Users/admin/Downloads/capcut_new/capcut_macos/config.py)**
    *   🇻🇳 Lưu trữ cấu hình tập trung (App ID, Device ID, tên giọng nói, ngôn ngữ). Điểm cấu hình duy nhất trên macOS.
    *   🇬🇧 Single source of truth config file containing device metadata, app versioning, and default voice profiles on macOS.
*   **[capcut_macos/cronet_helper.cpp](file:///Users/admin/Downloads/capcut_new/capcut_macos/cronet_helper.cpp)**
    *   🇻🇳 Mã nguồn C++ liên kết động với `libsscronet.dylib` của CapCut macOS để xử lý luồng mạng bất tuần tự thông qua CFRunLoop.
    *   🇬🇧 Native C++ source using dynamic loading (`dlopen`/`dlsym`) for `libsscronet.dylib` and executing asynchronous requests inside a `CFRunLoop`.

---

### 🔑 Windows Component (`capcut_windows/`)
*   **[capcut_windows/capcut_tts_ctypes.py](file:///Users/admin/Downloads/capcut_new/capcut_windows/capcut_tts_ctypes.py)**
    *   🇻🇳 Kịch bản Python chạy trên Windows. Giao tiếp trực tiếp với `cronet_helper.dll` thông qua ctypes để thực hiện gửi request mạng Cronet.
    *   🇬🇧 The main Python client on Windows, interfacing directly with compiled helper DLL using Python's `ctypes`.
*   **[capcut_windows/config.py](file:///Users/admin/Downloads/capcut_new/capcut_windows/config.py)**
    *   🇻🇳 Cấu hình hệ thống Windows bao gồm tham số thiết bị và đường dẫn tuyệt đối dẫn tới `sscronet.dll`.
    *   🇬🇧 Config manager containing device values and absolute path to the local CapCut `sscronet.dll` library.
*   **[capcut_windows/cronet_client.py](file:///Users/admin/Downloads/capcut_new/capcut_windows/cronet_client.py)**
    *   🇻🇳 Thư viện Python ctypes wrapper nạp trực tiếp `cronet_helper.dll` và thực thi truy xuất mạng.
    *   🇬🇧 A thin Python ctypes wrapper managing memory mapping and exports of `cronet_helper.dll`.
*   **[capcut_windows/cronet_helper_dll.cpp](file:///Users/admin/Downloads/capcut_new/capcut_windows/cronet_helper_dll.cpp)**
    *   🇻🇳 Mã nguồn C++ biên dịch thành thư viện động DLL trên Windows sử dụng Win32 API và Cronet engine.
    *   🇬🇧 C++ DLL source designed for Windows, wrapping Cronet calls with custom export interfaces.
*   **[capcut_windows/build.bat](file:///Users/admin/Downloads/capcut_new/capcut_windows/build.bat)**
    *   🇻🇳 Script tự động biên dịch C++ Windows qua trình biên dịch MSVC (cl.exe).
    *   🇬🇧 Automated batch build file invoking Microsoft Visual C++ Compiler (`cl.exe`).

---

## 🛠️ 2. Build Instructions / Hướng Dẫn Biên Dịch C++

### 🍏 On macOS:
> [!NOTE]
> Kịch bản Python `capcut_tts_ctypes.py` sẽ **tự động kiểm tra và biên dịch** mã nguồn C++ tại lần chạy đầu tiên. Nếu muốn biên dịch thủ công, sử dụng lệnh bên dưới.
>
> The Python driver automatically compiles this on the fly. To compile manually, run the following:

```bash
cd capcut_macos
clang++ -O3 -std=c++17 -framework CoreFoundation -framework Foundation cronet_helper.cpp -o cronet_helper
```

### 🔑 On Windows:
1. Mở công cụ **Developer Command Prompt for VS** (Để nạp các biến môi trường MSVC `cl.exe`).
2. Di chuyển tới thư mục `capcut_windows` và chạy kịch bản biên dịch:
```cmd
cd capcut_windows
build.bat
```
*Trình biên dịch sẽ tạo ra file thư viện động `cronet_helper.dll`.*

---

## 📂 3. Locating Cronet Engine / Hướng Dẫn Tìm Đường Dẫn Thư Viện Mạng

> [!WARNING]
> CapCut chặn hầu hết các thư viện HTTP thông thường (`requests`, `urllib`). Bạn bắt buộc phải chỉ định đúng đường dẫn thư viện Cronet của CapCut để vượt qua tường lửa.
>
> CapCut blocks standard Python HTTP clients. You must link against CapCut's authentic Cronet network library.

#### 🍏 macOS (`libsscronet.dylib`):
*   **Default Path / Đường dẫn mặc định:** `/Applications/CapCut.app/Contents/Frameworks/libsscronet.dylib`
*   *Nếu CapCut được cài đặt ở thư mục ứng dụng mặc định, hệ thống sẽ tự nạp thành công mà không cần cấu hình thêm.*

#### 🔑 Windows (`sscronet.dll`):
1. Nhấn tổ hợp `Windows + R`, gõ `%localappdata%\CapCut\Apps` và bấm `Enter`.
2. Mở thư mục mang tên phiên bản hiện tại (Ví dụ: `8.7.0.3685`).
3. Tìm file `sscronet.dll`, giữ phím `Shift` + chuột phải và chọn **Copy as path** (Sao chép đường dẫn).
4. Dán đường dẫn này vào biến `SSCRONET_DLL` trong tệp [capcut_windows/config.py](file:///Users/admin/Downloads/capcut_new/capcut_windows/config.py) dưới dạng raw string:
   `SSCRONET_DLL = r"C:\Users\<Tên_User>\AppData\Local\CapCut\Apps\8.7.0.3685\sscronet.dll"`

---

## 🔍 4. Proxy Capture & Reversing / Hướng Dẫn Bắt Gói Tin & Reverse API

Để lấy chính xác `voice name` và `resource_id` cho các giọng đọc độc quyền, He cần bắt gói tin HTTPS.

### Steps / Các Bước Thực Hiện:
1. **Setup Proxy / Cài đặt proxy:** Cài đặt công cụ phân tích mạng (Proxyman / Charles Proxy / Fiddler). Cài đặt chứng chỉ Root để bật giải mã HTTPS (SSL Decryption).
2. **Trigger Request / Gửi gói tin:** Mở CapCut Desktop và thực hiện thao tác Thêm Phụ Đề (Auto Captions) hoặc Đọc Văn Bản (Text-to-Speech).
3. **Capture Target URL / Lọc gói tin:** Tìm URL khớp với định dạng:
   ```http
   https://editor-api-sg.capcutapi.com/lv/v1/common_task/new?app_name=CapCut&device_type=MacBookPro17,1...
   ```
4. **Extract Parameter / Trích xuất giá trị:**
   *   Mở tab JSON Body của gói tin vừa bắt. Tìm trường cấu trúc dữ liệu `ssml`.
   *   Trích xuất tên giọng đọc tại thuộc tính `name` (Ví dụ: `DiT_zh_male_xionger`) và mã giọng đọc tại `resource_id` (Ví dụ: `7564318793716059409`).
   *   Thay các giá trị này vào file `config.py` để sử dụng giọng đọc đó.

### Reversing Mechanism / Cơ Chế Ký Xác Thực:
*   **x-ss-stub / x-ss-stub Header:** MD5 Hash của toàn bộ Request JSON Body.
*   **Sign Header:** Sử dụng chuỗi salt đặc trưng được băm MD5 để xác thực request:
    `MD5("9e2c|" + url_path_suffix + "|3|" + app_version + "|" + device_time + "|" + device_id + "|11ac")`
*   **Body Sign:** SSML được mã hóa bất đối xứng RSA-PKCS1v15 từ mã hash MD5 của cấu trúc SSML kèm các giá trị ID thiết bị để đảm bảo tính chống can thiệp.

---

## 🚀 5. How to Run / Cách Vận Hành Dự Án

### 🍏 macOS:
```bash
cd capcut_macos
python3 capcut_tts_ctypes.py "Chào anh, đây là giọng nói thử nghiệm."
```

### 🔑 Windows:
```cmd
cd capcut_windows
python capcut_tts_ctypes.py "Chào anh, đây là giọng nói thử nghiệm."
```
