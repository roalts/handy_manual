// Pinch-zoom for scanned pages, in its own chunk so react-zoom-pan-pinch loads only with an image.

import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";

interface Props {
  src: string;
  alt: string;
  onLoad: () => void;
  onError: () => void;
}

/** Double-tap toggles zoom; zoom stays between 1× and 5×. */
export default function ZoomableImage({ src, alt, onLoad, onError }: Props) {
  return (
    <div className="overflow-hidden rounded-md border border-line bg-paper-soft">
      <TransformWrapper doubleClick={{ mode: "toggle", step: 1.5 }} maxScale={5} minScale={1} panning={{ velocityDisabled: true }}>
        <TransformComponent wrapperStyle={{ width: "100%" }} contentStyle={{ width: "100%" }}>
          <img alt={alt} className="block h-auto w-full" decoding="async" onError={onError} onLoad={onLoad} src={src} />
        </TransformComponent>
      </TransformWrapper>
    </div>
  );
}
