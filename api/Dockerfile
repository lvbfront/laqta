FROM python:3.11-slim

# System deps:
# - libvips42/libvips-dev for pyvips (thumbnailing/watermarking)
# - libgl1/libglib2.0-0 for opencv-python-headless / insightface
# - fonts-dejavu-core (Latin) + fonts-noto-naskh-arabic (Arabic) so
#   pyvips' text()-based watermark has glyphs to render the bilingual
#   "Laqta · لقطة" mark with -- libvips pulls in pango/fontconfig
#   transitively via libvips42, but ships no actual font files, and
#   DejaVu alone has no Arabic coverage (RTL/Arabic is core to this
#   product, not an afterthought -- see CLAUDE.md).
# - build-essential for any wheels that need compiling on arm64
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libvips42 \
    libvips-dev \
    libgl1 \
    libglib2.0-0 \
    fonts-dejavu-core \
    fonts-noto-core \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
