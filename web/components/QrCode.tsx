"use client";

import { useEffect, useRef } from "react";
import QRCode from "qrcode";

export function QrCode({ value, size = 160 }: { value: string; size?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    QRCode.toCanvas(canvasRef.current, value, { width: size, margin: 1 }).catch(() => {
      // rendering failure just leaves a blank canvas -- not worth a whole error state
    });
  }, [value, size]);

  return <canvas ref={canvasRef} width={size} height={size} className="rounded-lg" />;
}
