import streamlit as st
import midtransclient
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import uuid
import io
from datetime import datetime
import streamlit.components.v1 as components
import base64

# --- KONFIGURASI & KONSTANTA ---
MIDTRANS_SERVER_KEY = 'Mid-server-FcYKPYk-LPZ348PE3inpCkrk'
MIDTRANS_CLIENT_KEY = 'Mid-client-rawLodn_Eyclj7vW'
PRICE_IDR = 5000

st.set_page_config(page_title="Self-Service Photobooth", page_icon="📸", layout="wide")

# --- TEMPLATE DEFINITIONS ---
TEMPLATES = {
    "2x2": {
        "name": "📸 2x2 Classic",
        "description": "4 foto dalam layout 2x2",
        "grid": (2, 2),
        "photo_size": (400, 400),
        "spacing": 20,
        "border": 30,
        "bg_color": (255, 255, 255)
    },
    "3x3": {
        "name": "🎨 3x3 Grid",
        "description": "9 foto dalam layout 3x3",
        "grid": (3, 3),
        "photo_size": (300, 300),
        "spacing": 15,
        "border": 25,
        "bg_color": (240, 240, 240)
    },
    "4x4": {
        "name": "✨ 4x4 Mega",
        "description": "16 foto dalam layout 4x4",
        "grid": (4, 4),
        "photo_size": (250, 250),
        "spacing": 10,
        "border": 20,
        "bg_color": (250, 250, 250)
    },
    "2x3": {
        "name": "📷 2x3 Portrait",
        "description": "6 foto dalam layout 2x3 vertikal",
        "grid": (2, 3),
        "photo_size": (350, 350),
        "spacing": 15,
        "border": 25,
        "bg_color": (255, 248, 240)
    },
    "3x2": {
        "name": "🌅 3x2 Landscape",
        "description": "6 foto dalam layout 3x2 horizontal",
        "grid": (3, 2),
        "photo_size": (350, 350),
        "spacing": 15,
        "border": 25,
        "bg_color": (240, 248, 255)
    },
    "strip": {
        "name": "🎞️ Film Strip",
        "description": "4 foto dalam strip vertikal",
        "grid": (1, 4),
        "photo_size": (400, 300),
        "spacing": 10,
        "border": 20,
        "bg_color": (0, 0, 0),
        "text_color": (255, 255, 255)
    }
}

# --- STATE MANAGEMENT ---
if 'step' not in st.session_state:
    st.session_state.step = 'template_select'
if 'captured_images' not in st.session_state:
    st.session_state.captured_images = []
if 'order_id' not in st.session_state:
    st.session_state.order_id = None
if 'payment_url' not in st.session_state:
    st.session_state.payment_url = None
if 'selected_template' not in st.session_state:
    st.session_state.selected_template = '2x2'
if 'countdown' not in st.session_state:
    st.session_state.countdown = 0
if 'camera_key' not in st.session_state:
    st.session_state.camera_key = 0
if 'last_photo_data' not in st.session_state:
    st.session_state.last_photo_data = None

# --- UTILS: TEMPLATE PROCESSING ---
def create_photobooth_grid(images, template_key):
    """Membuat grid photobooth dari list gambar."""
    template = TEMPLATES[template_key]
    rows, cols = template['grid']
    photo_width, photo_height = template['photo_size']
    spacing = template['spacing']
    border = template['border']
    bg_color = template['bg_color']
    
    # Calculate canvas size
    canvas_width = (photo_width * cols) + (spacing * (cols - 1)) + (border * 2)
    canvas_height = (photo_height * rows) + (spacing * (rows - 1)) + (border * 2)
    
    # Create canvas
    canvas = Image.new('RGB', (canvas_width, canvas_height), bg_color)
    
    # Paste images in grid
    total_photos = rows * cols
    for idx in range(total_photos):
        if idx < len(images):
            img = images[idx].copy()
        else:
            # Use last image if we don't have enough
            img = images[-1].copy() if images else Image.new('RGB', template['photo_size'], (200, 200, 200))
        
        # Resize to fit
        img.thumbnail(template['photo_size'], Image.Resampling.LANCZOS)
        
        # Calculate position
        row = idx // cols
        col = idx % cols
        
        x = border + (col * (photo_width + spacing))
        y = border + (row * (photo_height + spacing))
        
        # Paste image
        canvas.paste(img, (x, y))
    
    # Add decorative elements
    draw = ImageDraw.Draw(canvas)
    
    # Add date/time stamp for film strip
    if template_key == 'strip':
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        text_color = template.get('text_color', (255, 255, 255))
        draw.text((border, canvas_height - border + 5), f"📸 {timestamp}", fill=text_color, font=font)
    
    return canvas

def add_watermark(image_pil, text="UNPAID PREVIEW"):
    """Menambahkan watermark pada gambar untuk preview sebelum bayar."""
    watermarked = image_pil.copy().convert("RGBA")
    width, height = watermarked.size
    
    txt_layer = Image.new('RGBA', watermarked.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_layer)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
    except:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (width - text_width) / 2
    y = (height - text_height) / 2
    
    draw.text((x, y), text, fill=(255, 0, 0, 180), font=font)
    
    return Image.alpha_composite(watermarked, txt_layer).convert("RGB")

def convert_cv2_to_pil(cv2_img):
    """Konversi format OpenCV (BGR) ke Pillow (RGB)."""
    return Image.fromarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB))

def process_camera_image(uploaded_file):
    """Process image from camera input."""
    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        # Flip horizontal untuk efek mirror
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        return image
    return None

def camera_input_component():
    """HTML5 Camera Component with mirror effect"""
    html_code = """
    <div style="text-align: center;">
        <video id="video" width="640" height="480" autoplay style="transform: scaleX(-1); border: 2px solid #ddd; border-radius: 10px;"></video>
        <br><br>
        <button onclick="takePhoto()" style="padding: 15px 30px; font-size: 18px; background: #ff4b4b; color: white; border: none; border-radius: 5px; cursor: pointer;">📸 Ambil Foto</button>
        <canvas id="canvas" width="640" height="480" style="display:none;"></canvas>
    </div>
    
    <script>
        const video = document.getElementById('video');
        const canvas = document.getElementById('canvas');
        const context = canvas.getContext('2d');
        
        // Access camera
        navigator.mediaDevices.getUserMedia({ video: true })
            .then(stream => {
                video.srcObject = stream;
            })
            .catch(err => {
                console.error("Error accessing camera:", err);
            });
        
        function takePhoto() {
            // Draw image normally first
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            // Convert to base64 and send to Streamlit
            const imageData = canvas.toDataURL('image/jpeg');
            window.parent.postMessage({
                type: 'streamlit:setComponentValue',
                value: imageData
            }, '*');
        }
    </script>
    """
    return components.html(html_code, height=600)

# --- UTILS: PAYMENT MIDTRANS ---
def create_transaction(order_id, amount):
    """Membuat transaksi SNAP Midtrans."""
    snap = midtransclient.Snap(
        is_production=False,
        server_key=MIDTRANS_SERVER_KEY,
        client_key=MIDTRANS_CLIENT_KEY
    )
    
    param = {
        "transaction_details": {
            "order_id": order_id,
            "gross_amount": amount
        },
        "credit_card": {
            "secure": True
        },
        "item_details": [{
            "id": "PHOTO-001",
            "price": amount,
            "quantity": 1,
            "name": "Photobooth Session"
        }]
    }
    
    try:
        transaction = snap.create_transaction(param)
        return transaction['redirect_url']
    except Exception as e:
        st.error(f"Gagal membuat transaksi Midtrans: {e}")
        return None

def check_payment_status(order_id):
    """Cek status transaksi via Core API."""
    core = midtransclient.CoreApi(
        is_production=False,
        server_key=MIDTRANS_SERVER_KEY,
        client_key=MIDTRANS_CLIENT_KEY
    )
    
    try:
        status_response = core.transactions.status(order_id)
        transaction_status = status_response.get('transaction_status', '')
        fraud_status = status_response.get('fraud_status', '')
        
        if transaction_status == 'capture':
            if fraud_status == 'challenge':
                return 'pending'
            elif fraud_status == 'accept':
                return 'success'
        elif transaction_status == 'settlement':
            return 'success'
        elif transaction_status in ['cancel', 'deny', 'expire']:
            return 'failed'
        elif transaction_status == 'pending':
            return 'pending'
        
        return 'pending'
    except Exception as e:
        return 'pending'

# --- UI UTAMA ---
st.title("📸 Photobooth Self-Service")
st.markdown("---")

# SIDEBAR
with st.sidebar:
    st.header("📋 Info Session")
    st.write(f"**Step:** {st.session_state.step}")
    st.write(f"**Template:** {st.session_state.selected_template}")
    st.write(f"**Foto diambil:** {len(st.session_state.captured_images)}")
    
    if st.session_state.selected_template in TEMPLATES:
        template = TEMPLATES[st.session_state.selected_template]
        total_needed = template['grid'][0] * template['grid'][1]
        st.progress(len(st.session_state.captured_images) / total_needed)
        st.caption(f"{len(st.session_state.captured_images)}/{total_needed} foto")
    
    st.markdown("---")
    if st.button("🔄 Reset Aplikasi"):
        st.session_state.step = 'template_select'
        st.session_state.captured_images = []
        st.session_state.order_id = None
        st.session_state.payment_url = None
        st.session_state.selected_template = '2x2'
        st.session_state.camera_key = 0
        st.session_state.last_photo_data = None
        st.rerun()

# ===========================
# STEP 0: TEMPLATE SELECTION
# ===========================
if st.session_state.step == 'template_select':
    st.subheader("🎨 Pilih Layout Photobooth")
    st.write("Pilih berapa banyak foto yang ingin Anda ambil:")
    
    cols = st.columns(3)
    for idx, (key, template) in enumerate(TEMPLATES.items()):
        with cols[idx % 3]:
            st.markdown(f"### {template['name']}")
            st.caption(template['description'])
            
            rows, cols_grid = template['grid']
            total_photos = rows * cols_grid
            st.info(f"📸 Total: **{total_photos} foto**")
            
            # Create sample preview
            sample_size = template['photo_size']
            sample = Image.new('RGB', sample_size, (180, 180, 180))
            draw = ImageDraw.Draw(sample)
            
            # Draw sample face
            center_x, center_y = sample_size[0]//2, sample_size[1]//2
            draw.ellipse([center_x-30, center_y-30, center_x+30, center_y+30], fill=(255, 220, 180))
            draw.ellipse([center_x-15, center_y-10, center_x-5, center_y], fill=(50, 50, 50))
            draw.ellipse([center_x+5, center_y-10, center_x+15, center_y], fill=(50, 50, 50))
            draw.arc([center_x-20, center_y, center_x+20, center_y+20], 0, 180, fill=(200, 100, 100), width=3)
            
            samples = [sample.copy() for _ in range(total_photos)]
            preview = create_photobooth_grid(samples, key)
            preview.thumbnail((300, 400))
            st.image(preview, use_container_width=True)
            
            if st.button(f"Pilih Layout Ini", key=f"select_{key}", use_container_width=True, type="primary"):
                st.session_state.selected_template = key
                st.session_state.captured_images = []
                st.session_state.step = 'capture'
                st.rerun()

# ===========================
# STEP 1: CAPTURE MULTIPLE PHOTOS
# ===========================
elif st.session_state.step == 'capture':
    template = TEMPLATES[st.session_state.selected_template]
    rows, cols = template['grid']
    total_needed = rows * cols
    current_count = len(st.session_state.captured_images)
    
    st.subheader(f"📸 Sesi Pemotretan - {template['name']}")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Progress bar
        progress = current_count / total_needed
        st.progress(progress)
        st.write(f"**Foto {current_count + 1} dari {total_needed}**")
        
        if current_count < total_needed:
            st.info("📸 Klik tombol 'Ambil Foto' pada kamera di bawah")
            
            # Display camera component
            photo_data = camera_input_component()
            
            # Check if new photo data received
            if photo_data and photo_data != st.session_state.last_photo_data:
                try:
                    # Decode base64 image
                    image_data = photo_data.split(',')[1]
                    image_bytes = base64.b64decode(image_data)
                    image = Image.open(io.BytesIO(image_bytes))
                    
                    # MIRROR: Flip horizontal untuk konsisten dengan preview
                    image = image.transpose(Image.FLIP_LEFT_RIGHT)
                    
                    st.session_state.captured_images.append(image)
                    st.session_state.last_photo_data = photo_data
                    st.success(f"✅ Foto {len(st.session_state.captured_images)} berhasil diambil!")
                    
                    if len(st.session_state.captured_images) >= total_needed:
                        st.session_state.step = 'preview'
                    st.rerun()
                except Exception as e:
                    st.error(f"Error memproses foto: {e}")
            
            if current_count > 0:
                st.markdown("---")
                if st.button("⏭️ Lanjut ke Preview", width='stretch'):
                    st.session_state.step = 'preview'
                    st.rerun()
    
    with col2:
        st.write("**Tips Pose:**")
        poses = ["😊 Senyum natural", "🤪 Ekspresi lucu", "😎 Cool pose", "🤗 Peace sign", 
                 "🥰 Cute pose", "😂 Tertawa lepas", "🤔 Thinking pose", "✌️ Victory"]
        
        if current_count < len(poses):
            st.success(f"Pose #{current_count + 1}")
            st.write(f"**{poses[current_count]}**")
        
        st.markdown("---")
        
        # Show thumbnails
        if st.session_state.captured_images:
            st.write("**Foto Terkumpul:**")
            thumb_cols = st.columns(2)
            for i, img in enumerate(st.session_state.captured_images):
                with thumb_cols[i % 2]:
                    st.image(img, caption=f"Foto {i+1}", width='stretch')
        
        if st.button("⬅️ Ganti Template"):
            st.session_state.step = 'template_select'
            st.session_state.captured_images = []
            st.rerun()

# ===========================
# STEP 2: PREVIEW & PAYMENT
# ===========================
elif st.session_state.step == 'preview':
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.subheader("🖼️ Preview Hasil Photobooth")
        
        # Create grid
        grid_image = create_photobooth_grid(st.session_state.captured_images, st.session_state.selected_template)
        
        # Add watermark
        watermarked = add_watermark(grid_image)
        st.image(watermarked, caption="Preview (Watermarked)", width='stretch')
        
        col_retake, col_back = st.columns(2)
        with col_retake:
            if st.button("📸 Foto Ulang Semua"):
                st.session_state.step = 'capture'
                st.session_state.captured_images = []
                st.session_state.payment_url = None
                st.rerun()
        with col_back:
            if st.button("🎨 Ganti Template"):
                st.session_state.step = 'template_select'
                st.session_state.captured_images = []
                st.session_state.payment_url = None
                st.rerun()

    with col2:
        st.subheader("💳 Pembayaran")
        template = TEMPLATES[st.session_state.selected_template]
        st.success(f"Layout: **{template['name']}**")
        st.info(f"Total Biaya: **Rp {PRICE_IDR:,}**")
        
        if st.session_state.payment_url is None:
            if st.button("💳 Bayar via QRIS", type="primary", width='stretch'):
                new_order_id = f"ORDER-{uuid.uuid4().hex[:8]}"
                st.session_state.order_id = new_order_id
                
                with st.spinner("Membuat transaksi..."):
                    url = create_transaction(new_order_id, PRICE_IDR)
                    if url:
                        st.session_state.payment_url = url
                        st.rerun()
        else:
            st.success("Order ID Terbuat!")
            st.code(st.session_state.order_id)
            
            st.link_button("🔗 Buka Halaman Pembayaran (QRIS)", st.session_state.payment_url, use_container_width='stretch')
            st.caption("Scan QRIS pada link di atas, lalu klik tombol Cek Status.")
            
            st.markdown("---")
            if st.button("✅ Cek Status Pembayaran", type="primary", width='stretch'):
                with st.spinner("Memeriksa status pembayaran..."):
                    status = check_payment_status(st.session_state.order_id)
                    if status == 'success':
                        st.balloons()
                        st.session_state.step = 'paid'
                        st.rerun()
                    elif status == 'pending':
                        st.warning("Pembayaran belum terdeteksi.")
                    else:
                        st.error("Pembayaran Gagal atau Kadaluarsa.")

# ===========================
# STEP 3: DOWNLOAD
# ===========================
elif st.session_state.step == 'paid':
    st.subheader("🎉 Pembayaran Berhasil!")
    
    # Create final grid
    final_grid = create_photobooth_grid(st.session_state.captured_images, st.session_state.selected_template)
    
    st.image(final_grid, caption="Hasil Photobooth Anda", use_container_width=True)
    
    # Prepare download
    buf = io.BytesIO()
    final_grid.save(buf, format="JPEG", quality=95)
    byte_im = buf.getvalue()
    
    col_dl, col_new = st.columns(2)
    with col_dl:
        st.download_button(
            label="⬇️ Download Foto",
            data=byte_im,
            file_name=f"photobooth_{st.session_state.selected_template}_{st.session_state.order_id}.jpg",
            mime="image/jpeg",
            type="primary",
            use_container_width=True
        )
    with col_new:
        if st.button("🔄 Foto Baru", use_container_width=True):
            st.session_state.step = 'template_select'
            st.session_state.captured_images = []
            st.session_state.order_id = None
            st.session_state.payment_url = None
            st.rerun()
