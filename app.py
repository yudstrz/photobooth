import streamlit as st
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase
import midtransclient
from PIL import Image, ImageDraw, ImageFont
import cv2
import av
import numpy as np
import uuid
import time
import io

# --- KONFIGURASI & KONSTANTA ---
# GANTI DENGAN SERVER KEY & CLIENT KEY MIDTRANS SANDBOX ANDA
MIDTRANS_SERVER_KEY = 'SB-Mid-server-xxxxxxxxxxxx'
MIDTRANS_CLIENT_KEY = 'SB-Mid-client-xxxxxxxxxxxx'
PRICE_IDR = 5000  # Harga foto

st.set_page_config(page_title="Self-Service Photobooth", page_icon="📸")

# --- STATE MANAGEMENT ---
# Inisialisasi session state untuk menyimpan status aplikasi antar re-run
if 'step' not in st.session_state:
    st.session_state.step = 'capture' # capture, preview, paid
if 'captured_image' not in st.session_state:
    st.session_state.captured_image = None
if 'order_id' not in st.session_state:
    st.session_state.order_id = None
if 'payment_url' not in st.session_state:
    st.session_state.payment_url = None

# --- UTILS: IMAGE PROCESSING ---
def add_watermark(image_pil, text="UNPAID PREVIEW"):
    """Menambahkan watermark silang pada gambar untuk preview sebelum bayar."""
    watermarked = image_pil.copy().convert("RGBA")
    width, height = watermarked.size
    
    # Membuat layer transparan untuk text
    txt_layer = Image.new('RGBA', watermarked.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(txt_layer)
    
    # Coba load default font, jika gagal pakai default bitmap
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except:
        font = ImageFont.load_default()

    # Gambar text watermark di tengah
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    x = (width - text_width) / 2
    y = (height - text_height) / 2
    
    # Warna merah semi-transparan
    draw.text((x, y), text, fill=(255, 0, 0, 128), font=font)
    
    return Image.alpha_composite(watermarked, txt_layer)

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
        transaction_status = status_response['transaction_status']
        fraud_status = status_response['fraud_status']
        
        # Logika settlement Midtrans
        if transaction_status == 'capture':
            if fraud_status == 'challenge':
                return 'pending'
            elif fraud_status == 'accept':
                return 'success'
        elif transaction_status == 'settlement':
            return 'success'
        elif transaction_status == 'cancel' or transaction_status == 'deny' or transaction_status == 'expire':
            return 'failed'
        elif transaction_status == 'pending':
            return 'pending'
        
        return 'pending'
    except Exception as e:
        # Jika order_id belum ada di Midtrans (user belum scan QR)
        return 'pending'

# --- CLASS: WEBRTC PROCESSOR ---
class VideoTransformer(VideoTransformerBase):
    def __init__(self):
        self.frame = None

    def recv(self, frame):
        self.frame = frame
        return frame

# --- UI UTAMA ---
st.title("📸 Photobooth Self-Service")
st.markdown("---")

# SIDEBAR DEBUG
with st.sidebar:
    st.header("Debug Panel")
    st.write(f"Current Step: **{st.session_state.step}**")
    if st.button("Reset Aplikasi"):
        for key in st.session_state.keys():
            del st.session_state[key]
        st.rerun()

# ===========================
# STEP 1: LIVE BOOTH & CAPTURE
# ===========================
if st.session_state.step == 'capture':
    st.subheader("Step 1: Pose & Capture")
    
    # Setup WebRTC Streamer
    ctx = webrtc_streamer(
        key="photobooth", 
        video_processor_factory=VideoTransformer,
        rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
        media_stream_constraints={"video": True, "audio": False}
    )

    if ctx.video_transformer:
        if st.button("📸 Ambil Foto", type="primary", use_container_width=True):
            if ctx.video_transformer.frame:
                # Ambil frame terakhir dari video stream
                img = ctx.video_transformer.frame.to_ndarray(format="bgr24")
                # Simpan ke session state
                st.session_state.captured_image = convert_cv2_to_pil(img)
                st.session_state.step = 'preview'
                st.rerun()
            else:
                st.warning("Tunggu sampai kamera siap...")

# ===========================
# STEP 2 & 3: PREVIEW & PAYMENT
# ===========================
elif st.session_state.step == 'preview':
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.subheader("Preview Foto")
        # Tampilkan foto dengan watermark
        watermarked_img = add_watermark(st.session_state.captured_image)
        st.image(watermarked_img, caption="Preview (Watermarked)", use_column_width=True)
        
        if st.button("🔄 Foto Ulang"):
            st.session_state.step = 'capture'
            st.session_state.payment_url = None
            st.rerun()

    with col2:
        st.subheader("Pembayaran")
        st.info(f"Total Biaya: **Rp {PRICE_IDR:,}**")
        
        # Generate Transaction jika belum ada
        if st.session_state.payment_url is None:
            if st.button("💳 Bayar via QRIS", type="primary"):
                new_order_id = f"ORDER-{uuid.uuid4().hex[:8]}"
                st.session_state.order_id = new_order_id
                
                url = create_transaction(new_order_id, PRICE_IDR)
                if url:
                    st.session_state.payment_url = url
                    st.rerun()
        
        # Tampilkan Interface Pembayaran
        else:
            st.success("Order ID Terbuat!")
            # Tampilkan tombol link ke Midtrans Snap (atau iframe)
            st.link_button("🔗 Buka Halaman Pembayaran (QRIS)", st.session_state.payment_url)
            
            # Embed halaman pembayaran (Opsional, beberapa browser memblokir iframe payment)
            st.caption("Scan QRIS pada link di atas, lalu klik tombol Cek Status di bawah.")
            
            st.markdown("---")
            check_btn = st.button("✅ Cek Status Pembayaran", type="primary")
            
            if check_btn:
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
    
    # Tampilkan foto asli (Original)
    st.image(st.session_state.captured_image, caption="Hasil Foto Anda (Clean)", use_column_width=True)
    
    # Siapkan buffer untuk download
    buf = io.BytesIO()
    st.session_state.captured_image.save(buf, format="JPEG")
    byte_im = buf.getvalue()
    
    col_dl, col_new = st.columns(2)
    with col_dl:
        st.download_button(
            label="⬇️ Download Foto JPEG",
            data=byte_im,
            file_name="photobooth_result.jpg",
            mime="image/jpeg",
            type="primary"
        )
    with col_new:
        if st.button("🏠 Foto Baru"):
            # Reset state
            st.session_state.step = 'capture'
            st.session_state.captured_image = None
            st.session_state.order_id = None
            st.session_state.payment_url = None
            st.rerun()
