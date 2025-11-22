import streamlit as st
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase, WebRtcMode
import midtransclient
from PIL import Image, ImageDraw, ImageFont
import cv2
import av
import numpy as np
import uuid
import io

# --- KONFIGURASI & KONSTANTA ---
# GANTI DENGAN SERVER KEY & CLIENT KEY MIDTRANS SANDBOX ANDA
MIDTRANS_SERVER_KEY = 'Mid-server-FcYKPYk-LPZ348PE3inpCkrk'
MIDTRANS_CLIENT_KEY = 'Mid-client-rawLodn_Eyclj7vW'
PRICE_IDR = 5000  # Harga foto

st.set_page_config(page_title="Self-Service Photobooth", page_icon="📸", layout="wide")

# --- TEMPLATE DEFINITIONS ---
TEMPLATES = {
    "classic": {
        "name": "🎨 Classic",
        "description": "Frame klasik dengan border putih",
        "color": (255, 255, 255),
        "border_width": 30
    },
    "polaroid": {
        "name": "📷 Polaroid",
        "description": "Style polaroid vintage",
        "color": (245, 245, 220),
        "border_width": 40,
        "bottom_extra": 80
    },
    "neon": {
        "name": "✨ Neon",
        "description": "Border neon warna-warni",
        "color": (255, 20, 147),
        "border_width": 25,
        "gradient": True
    },
    "minimalist": {
        "name": "⬜ Minimalist",
        "description": "Border tipis minimalis",
        "color": (240, 240, 240),
        "border_width": 15
    },
    "party": {
        "name": "🎉 Party",
        "description": "Frame pesta dengan confetti",
        "color": (255, 215, 0),
        "border_width": 35,
        "decorations": True
    },
    "romantic": {
        "name": "💕 Romantic",
        "description": "Frame romantic pink",
        "color": (255, 192, 203),
        "border_width": 30,
        "hearts": True
    }
}

# --- STATE MANAGEMENT ---
if 'step' not in st.session_state:
    st.session_state.step = 'template_select'
if 'captured_image' not in st.session_state:
    st.session_state.captured_image = None
if 'order_id' not in st.session_state:
    st.session_state.order_id = None
if 'payment_url' not in st.session_state:
    st.session_state.payment_url = None
if 'selected_template' not in st.session_state:
    st.session_state.selected_template = 'classic'

# --- UTILS: TEMPLATE PROCESSING ---
def apply_template(image_pil, template_key):
    """Menerapkan template/frame pada foto."""
    template = TEMPLATES[template_key]
    
    # Setup
    border_width = template['border_width']
    bottom_extra = template.get('bottom_extra', 0)
    
    # Calculate new size
    new_width = image_pil.width + (border_width * 2)
    new_height = image_pil.height + (border_width * 2) + bottom_extra
    
    # Create base with border color
    if template.get('gradient'):
        # Create gradient background
        base = Image.new('RGB', (new_width, new_height))
        draw = ImageDraw.Draw(base)
        for i in range(new_height):
            r = int(255 * (1 - i/new_height) + 20 * (i/new_height))
            g = int(20 * (1 - i/new_height) + 147 * (i/new_height))
            b = int(147 * (1 - i/new_height) + 255 * (i/new_height))
            draw.rectangle([(0, i), (new_width, i+1)], fill=(r, g, b))
    else:
        base = Image.new('RGB', (new_width, new_height), template['color'])
    
    # Paste photo
    base.paste(image_pil, (border_width, border_width))
    
    # Add decorations
    draw = ImageDraw.Draw(base)
    
    if template.get('decorations'):
        # Add confetti dots
        for _ in range(50):
            x = np.random.randint(0, new_width)
            y = np.random.randint(0, new_height)
            size = np.random.randint(3, 8)
            color = tuple(np.random.randint(0, 255, 3).tolist())
            draw.ellipse([x, y, x+size, y+size], fill=color)
    
    if template.get('hearts'):
        # Add corner hearts
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        except:
            font = ImageFont.load_default()
        for pos in [(10, 10), (new_width-40, 10), (10, new_height-40), (new_width-40, new_height-40)]:
            draw.text(pos, "💕", font=font, fill=(255, 105, 180))
    
    # Add text for polaroid style
    if template_key == 'polaroid':
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except:
            font = ImageFont.load_default()
        
        text = "Photobooth Memories ✨"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_x = (new_width - text_width) // 2
        text_y = new_height - bottom_extra + 20
        draw.text((text_x, text_y), text, fill=(100, 100, 100), font=font)
    
    return base

def add_watermark(image_pil, text="UNPAID PREVIEW"):
    """Menambahkan watermark silang pada gambar untuk preview sebelum bayar."""
    watermarked = image_pil.copy().convert("RGBA")
    width, height = watermarked.size
    
    # Membuat layer transparan untuk text
    txt_layer = Image.new('RGBA', watermarked.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_layer)
    
    # Load font
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
    except:
        font = ImageFont.load_default()

    # Gambar text watermark di tengah
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (width - text_width) / 2
    y = (height - text_height) / 2
    
    # Warna merah semi-transparan
    draw.text((x, y), text, fill=(255, 0, 0, 180), font=font)
    
    return Image.alpha_composite(watermarked, txt_layer).convert("RGB")

def convert_cv2_to_pil(cv2_img):
    """Konversi format OpenCV (BGR) ke Pillow (RGB)."""
    return Image.fromarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB))

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
        
        # Logika settlement Midtrans
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

# --- CLASS: WEBRTC PROCESSOR ---
class VideoTransformer(VideoTransformerBase):
    def __init__(self):
        self.last_frame = None

    def transform(self, frame):
        img = frame.to_ndarray(format="bgr24")
        # Flip horizontal untuk efek mirror (seperti kamera depan HP)
        img_flipped = cv2.flip(img, 1)
        # Simpan frame yang sudah di-flip untuk capture
        self.last_frame = img_flipped
        return av.VideoFrame.from_ndarray(img_flipped, format="bgr24")

# --- UI UTAMA ---
st.title("📸 Photobooth Self-Service")
st.markdown("---")

# SIDEBAR DEBUG
with st.sidebar:
    st.header("Debug Panel")
    st.write(f"Current Step: **{st.session_state.step}**")
    st.write(f"Template: **{st.session_state.selected_template}**")
    if st.button("Reset Aplikasi"):
        st.session_state.step = 'template_select'
        st.session_state.captured_image = None
        st.session_state.order_id = None
        st.session_state.payment_url = None
        st.session_state.selected_template = 'classic'
        st.rerun()

# ===========================
# STEP 0: TEMPLATE SELECTION
# ===========================
if st.session_state.step == 'template_select':
    st.subheader("🎨 Pilih Template Frame")
    st.write("Pilih template frame untuk foto Anda:")
    
    # Display templates in grid
    cols = st.columns(3)
    for idx, (key, template) in enumerate(TEMPLATES.items()):
        with cols[idx % 3]:
            st.markdown(f"### {template['name']}")
            st.caption(template['description'])
            
            # Create sample preview
            sample = Image.new('RGB', (200, 200), (200, 200, 200))
            sample_with_frame = apply_template(sample, key)
            sample_with_frame.thumbnail((300, 300))
            st.image(sample_with_frame, use_container_width=True)
            
            if st.button(f"Pilih {template['name']}", key=f"select_{key}", use_container_width=True):
                st.session_state.selected_template = key
                st.session_state.step = 'capture'
                st.rerun()

# ===========================
# STEP 1: LIVE BOOTH & CAPTURE
# ===========================
elif st.session_state.step == 'capture':
    st.subheader("Step 1: Pose & Capture")
    
    # Show selected template
    template = TEMPLATES[st.session_state.selected_template]
    st.info(f"Template terpilih: **{template['name']}** - {template['description']}")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Setup WebRTC Streamer
        ctx = webrtc_streamer(
            key="photobooth", 
            video_processor_factory=VideoTransformer,
            mode=WebRtcMode.SENDRECV,
            rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
            media_stream_constraints={"video": True, "audio": False},
            async_processing=True,
        )

        if ctx.video_processor:
            if st.button("📸 Ambil Foto", type="primary", use_container_width=True):
                if hasattr(ctx.video_processor, 'last_frame') and ctx.video_processor.last_frame is not None:
                    img = ctx.video_processor.last_frame
                    st.session_state.captured_image = convert_cv2_to_pil(img)
                    st.session_state.step = 'preview'
                    st.rerun()
                else:
                    st.warning("Tunggu sampai kamera siap...")
    
    with col2:
        st.write("**Tips:**")
        st.write("✓ Pastikan pencahayaan cukup")
        st.write("✓ Posisikan wajah di tengah")
        st.write("✓ Berikan senyum terbaik!")
        
        if st.button("⬅️ Ganti Template"):
            st.session_state.step = 'template_select'
            st.rerun()

# ===========================
# STEP 2 & 3: PREVIEW & PAYMENT
# ===========================
elif st.session_state.step == 'preview':
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.subheader("Preview Foto")
        
        # Apply template to captured image
        templated_image = apply_template(st.session_state.captured_image, st.session_state.selected_template)
        
        # Add watermark
        watermarked_img = add_watermark(templated_image)
        st.image(watermarked_img, caption="Preview (Watermarked)", use_container_width=True)
        
        col_retake, col_template = st.columns(2)
        with col_retake:
            if st.button("🔄 Foto Ulang"):
                st.session_state.step = 'capture'
                st.session_state.payment_url = None
                st.rerun()
        with col_template:
            if st.button("🎨 Ganti Template"):
                st.session_state.step = 'template_select'
                st.session_state.payment_url = None
                st.rerun()

    with col2:
        st.subheader("Pembayaran")
        template = TEMPLATES[st.session_state.selected_template]
        st.success(f"Template: **{template['name']}**")
        st.info(f"Total Biaya: **Rp {PRICE_IDR:,}**")
        
        # Generate Transaction jika belum ada
        if st.session_state.payment_url is None:
            if st.button("💳 Bayar via QRIS", type="primary", use_container_width=True):
                new_order_id = f"ORDER-{uuid.uuid4().hex[:8]}"
                st.session_state.order_id = new_order_id
                
                with st.spinner("Membuat transaksi..."):
                    url = create_transaction(new_order_id, PRICE_IDR)
                    if url:
                        st.session_state.payment_url = url
                        st.rerun()
        
        # Tampilkan Interface Pembayaran
        else:
            st.success("Order ID Terbuat!")
            st.code(st.session_state.order_id)
            
            st.link_button("🔗 Buka Halaman Pembayaran (QRIS)", st.session_state.payment_url, use_container_width=True)
            
            st.caption("Scan QRIS pada link di atas, lalu klik tombol Cek Status di bawah.")
            
            st.markdown("---")
            check_btn = st.button("✅ Cek Status Pembayaran", type="primary", use_container_width=True)
            
            if check_btn:
                with st.spinner("Memeriksa status pembayaran..."):
                    status = check_payment_status(st.session_state.order_id)
                    if status == 'success':
                        st.balloons()
                        st.session_state.step = 'paid'
                        st.rerun()
                    elif status == 'pending':
                        st.warning("Pembayaran belum terdeteksi. Silakan selesaikan pembayaran.")
                    else:
                        st.error("Pembayaran Gagal atau Kadaluarsa.")

# ===========================
# STEP 4: UNLOCK & DOWNLOAD
# ===========================
elif st.session_state.step == 'paid':
    st.subheader("🎉 Pembayaran Berhasil!")
    
    # Apply template to final image
    final_image = apply_template(st.session_state.captured_image, st.session_state.selected_template)
    
    # Tampilkan foto asli dengan template
    st.image(final_image, caption="Hasil Foto Anda (Clean)", use_container_width=True)
    
    # Siapkan buffer untuk download
    buf = io.BytesIO()
    final_image.save(buf, format="JPEG", quality=95)
    byte_im = buf.getvalue()
    
    col_dl, col_new = st.columns(2)
    with col_dl:
        st.download_button(
            label="⬇️ Download Foto JPEG",
            data=byte_im,
            file_name=f"photobooth_{st.session_state.selected_template}.jpg",
            mime="image/jpeg",
            type="primary",
            use_container_width=True
        )
    with col_new:
        if st.button("🏠 Foto Baru", use_container_width=True):
            st.session_state.step = 'template_select'
            st.session_state.captured_image = None
            st.session_state.order_id = None
            st.session_state.payment_url = None
            st.rerun()
