# CapCut TTS & ASR API Client

Dự án cung cấp thư viện Python kết nối trực tiếp đến API CapCut (TTS - Text to Speech và ASR - Speech to Text) mà không cần chạy giao diện ứng dụng. Dự án hỗ trợ đa nền tảng (macOS và Windows).

---

## 📂 Cấu Trúc Dự Án

*   **Dành cho macOS (Thư mục `capcut_macos/`):**
    *   [capcut_macos/capcut_tts_ctypes.py](file:///Users/admin/Downloads/capcut_new/capcut_macos/capcut_tts_ctypes.py): Kịch bản chính trên macOS, sử dụng ctypes để gọi và biên dịch `cronet_helper.cpp` thành binary hỗ trợ gửi request qua Cronet.
    *   [capcut_macos/config.py](file:///Users/admin/Downloads/capcut_new/capcut_macos/config.py): File cấu hình tập trung chứa thông tin thiết bị, ứng dụng, và giọng đọc (Single Source of Truth).
    *   [capcut_macos/cronet_helper.cpp](file:///Users/admin/Downloads/capcut_new/capcut_macos/cronet_helper.cpp): Cầu nối C++ gọi thư viện mạng `libsscronet` của CapCut macOS.
*   **Dành cho Windows (Thư mục `capcut_windows/`):**
    *   [capcut_windows/capcut_tts_ctypes.py](file:///Users/admin/Downloads/capcut_new/capcut_windows/capcut_tts_ctypes.py): Kịch bản chính chạy trên Windows, tương thích hoàn toàn cấu hình.
    *   [capcut_windows/config.py](file:///Users/admin/Downloads/capcut_new/capcut_windows/config.py): File cấu hình tập trung cho Windows.
    *   [capcut_windows/cronet_client.py](file:///Users/admin/Downloads/capcut_new/capcut_windows/cronet_client.py): Wrapper ctypes kết nối tới DLL của Cronet trên Windows.
    *   [capcut_windows/cronet_helper_dll.cpp](file:///Users/admin/Downloads/capcut_new/capcut_windows/cronet_helper_dll.cpp): File nguồn C++ biên dịch ra DLL trên Windows.

---

## ⚙️ Cấu Hình (config.py)

Cả macOS và Windows đều sử dụng file `config.py` riêng biệt để quản lý tham số. 

```python
# Ví dụ config.py cho macOS
APP_ID      = "359289"
APP_VR      = "8.6.0"
APP_CHANNEL = "App Store"

DEVICE_ID       = "7647183892936328721"
IID             = "7647185302080423697"
OS_VERSION      = "15.7.4"
DEVICE_TYPE     = "MacBookPro17,1"
DEVICE_PLATFORM = "mac"

VOICE_NAME        = "DiT_zh_male_xionger"
VOICE_RESOURCE_ID = "7564318793716059409"
VOICE_PLATFORM    = "sami"
VOICE_RATE        = "1.0"
```

### 📂 Hướng Dẫn Tìm Đường Dẫn Thư Viện Cronet (`sscronet.dll` / `libsscronet.dylib`)

Cơ chế gửi request của CapCut sử dụng thư viện mạng Cronet của Chromium được tùy biến. Dự án cần liên kết trực tiếp tới thư viện này để không bị chặn bởi tường lửa của TikTok/CapCut.

#### 1. Trên Windows (`sscronet.dll`):
Tệp tin `sscronet.dll` nằm trong thư mục cài đặt của ứng dụng CapCut.
*   **Đường dẫn mặc định:**
    `C:\Users\<Tên_User>\AppData\Local\CapCut\Apps\<Phiên_Bản_CapCut>\sscronet.dll`
*   **Cách lấy nhanh:**
    1. Nhấn tổ hợp phím `Windows + R`, nhập `%localappdata%\CapCut\Apps` và nhấn `Enter`.
    2. Truy cập vào thư mục phiên bản hiện tại (ví dụ: `8.7.0.3685`).
    3. Tìm file `sscronet.dll`. Nhấn giữ phím `Shift` và click chuột phải vào file, chọn **Copy as path** (Sao chép dưới dạng đường dẫn).
    4. Dán đường dẫn này vào biến `SSCRONET_DLL` trong file `capcut_windows/config.py`. *Lưu ý dùng tiền tố `r` (raw string), ví dụ:* `SSCRONET_DLL = r"C:\Users\K07VN\AppData\Local\CapCut\Apps\8.7.0.3685\sscronet.dll"`

#### 2. Trên macOS (`libsscronet.dylib`):
Thư viện này nằm trực tiếp bên trong App Bundle của CapCut.
*   **Đường dẫn mặc định:**
    `/Applications/CapCut.app/Contents/Frameworks/libsscronet.dylib`
*   **Chi tiết:**
    *   Nếu He cài đặt CapCut trong thư mục Ứng dụng mặc định của hệ thống (`/Applications`), đường dẫn này sẽ tự động chính xác và C++ helper (`cronet_helper.cpp`) sẽ gọi thành công mà không cần cấu hình thêm.
    *   Trong trường hợp cài đặt CapCut ở thư mục người dùng hoặc thư mục ứng dụng tùy chỉnh, hãy mở file [capcut_macos/cronet_helper.cpp](file:///Users/admin/Downloads/capcut_new/capcut_macos/cronet_helper.cpp) và sửa đường dẫn tại hàm `dlopen` ở dòng 125 tương ứng với vị trí thực tế của `libsscronet.dylib`.

---

## 🔍 Hướng Dẫn Bắt Payload API & Reverse-Engineering

Để lấy chính xác `voice name` (tên giọng đọc nội bộ) và `resource_id` của các giọng đọc khác trong CapCut, người dùng cần bắt gói tin mạng khi ứng dụng CapCut hoạt động.

### 1. Chuẩn Bị Công Cụ Proxy
Sử dụng các phần mềm bắt gói tin (Intercepting Proxy) phổ biến:
*   **Charles Proxy** hoặc **Proxyman** (Khuyên dùng trên macOS).
*   **Fiddler Classic** / **Fiddler Everywhere** (Khuyên dùng trên Windows).
*   **Burp Suite** (Dành cho chuyên gia).

### 2. Cài Đặt Chứng Chỉ SSL (SSL Decryption)
Vì CapCut sử dụng giao thức HTTPS bảo mật, bạn bắt buộc phải cài đặt và kích hoạt tin cậy chứng chỉ gốc (Root Certificate) của phần mềm Proxy trên máy tính thì mới có thể đọc được nội dung payload dạng JSON.

### 3. Bắt Gói Tin API Mục Tiêu
1. Mở phần mềm Proxy và bật tính năng SSL Proxying cho domain `*.capcutapi.com`.
2. Mở ứng dụng CapCut Desktop lên.
3. Thực hiện thao tác tạo phụ đề tự động (Auto Captions) hoặc sử dụng tính năng Text-to-Speech (Đọc văn bản).
4. Tìm gói tin có URL khớp hoặc tương tự định dạng dưới đây:
   ```http
   https://editor-api-sg.capcutapi.com/lv/v1/common_task/new?app_name=CapCut&device_type=MacBookPro17,1&os_version=15.7.4&channel=App%20Store&version_name=8.6.0&device_brand=MacBookPro17,1&babi_param=%7B%22feature_entrance%22%3A%22editor%22%2C%22feature_entrance_detail%22%3A%22editor-elements-captions-subtitle_recognition%22%2C%22feature_key%22%3A%22subtitle_recognition%22%2C%22scenario%22%3A%22video_editor%22%7D&device_id=7647183892936328721&iid=7647185302080423697&region=VN&version_code=8.6.0&device_platform=mac&aid=359289
   ```

### 4. Phân Tích Payload Đọc Gói Tin (Reverse API)
Nhấp vào gói tin POST được bắt, chọn tab **JSON / Raw Body** để xem nội dung payload gửi đi:

*   **Lấy `voice_name` và `resource_id`:**
    Trong JSON body, bạn tìm cấu trúc SSML được gửi lên nằm ở trường `"ssml"`. Nó có dạng:
    ```xml
    <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
        <voice name="DiT_zh_male_xionger" platform="sami" resource_id="7564318793716059409" ...>
            <prosody rate="1.0">...</prosody>
        </voice>
    </speak>
    ```
    Hãy copy giá trị của thuộc tính `name` (tức `DiT_zh_male_xionger`) điền vào `VOICE_NAME` và giá trị của thuộc tính `resource_id` (tức `7564318793716059409`) điền vào `VOICE_RESOURCE_ID` trong file `config.py`.

*   **Cơ chế ký mã nguồn (API Signing Reverse Engineering):**
    *   **Sign Header (`sign`):** Headers của request chứa chữ ký xác thực sinh ra theo quy luật:
        `MD5("9e2c|" + url_path_suffix + "|3|" + version + "|" + timestamp + "|" + device_id + "|11ac")`
    *   **Sign Body Payload:** Một tham số chữ ký mã hóa RSA-PKCS1v15 nằm trong body JSON giúp server kiểm soát toàn vẹn dữ liệu SSML. Định dạng dữ liệu thô đầu vào trước khi mã hóa bằng khóa công khai (Public Key):
        `appid:{APP_ID}&did:{DEVICE_ID}&creditDisable:false&ssml:{MD5(SSML)}&extraInfo:{EXTRA_INFO}`

---

## 🚀 Cách Chạy Dự Án

### Trên macOS:
1. Đảm bảo bạn đã cài đặt Python 3 và Xcode Command Line Tools (để có `clang++`).
2. Di chuyển vào thư mục `capcut_macos`:
   ```bash
   cd capcut_macos
   ```
3. Chạy kịch bản:
   ```bash
   python3 capcut_tts_ctypes.py "Nội dung văn bản cần đọc"
   ```
   Kịch bản sẽ tự động biên dịch `cronet_helper.cpp` nếu chưa có file thực thi, thực hiện ký payload và tải file audio TTS về.

### Trên Windows:
1. Di chuyển vào thư mục `capcut_windows`:
   ```cmd
   cd capcut_windows
   ```
2. Chạy file batch `build.bat` để biên dịch DLL trợ giúp (yêu cầu bộ biên dịch MSVC/g++).
3. Chạy lệnh:
   ```cmd
   python capcut_tts_ctypes.py "Nội dung văn bản cần đọc"
   ```
