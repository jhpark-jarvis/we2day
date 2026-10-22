type Coordinate = { lat(): number; lng(): number };
type Overlay = { setMap(map: MapInstance | null): void };
export type MapInstance = {
  fitBounds(bounds: unknown): void;
  setSize(size: { width: number; height: number }): void;
  destroy(): void;
};
type Maps = {
  Map: new (element: HTMLElement, options: object) => MapInstance;
  LatLng: new (lat: number, lng: number) => Coordinate;
  LatLngBounds: new (southwest: Coordinate, northeast: Coordinate) => unknown;
  Marker: new (options: object) => Overlay;
  Polyline: new (options: object) => Overlay;
  Event: {
    addListener(
      map: MapInstance,
      name: string,
      callback: (event: { coord: Coordinate }) => void,
    ): unknown;
    removeListener(listener: unknown): void;
  };
};
declare global {
  interface Window {
    naver?: { maps: Maps };
    we2dayMapReady?: () => void;
    navermap_authFailure?: () => void;
  }
}
let loading: Promise<Maps> | undefined;
export function loadNaverMap(key: string): Promise<Maps> {
  if (loading) return loading;
  loading = new Promise<Maps>((resolve, reject) => {
    const script = document.createElement("script");
    const timeout = window.setTimeout(
      () => fail("지도 응답을 기다리는 시간이 초과됐어요. 지도를 닫았다 다시 열어 주세요."),
      15000,
    );
    const fail = (message: string) => {
      window.clearTimeout(timeout);
      script.remove();
      loading = undefined;
      reject(new Error(message));
    };
    window.we2dayMapReady = () => {
      if (window.naver?.maps?.Map) {
        window.clearTimeout(timeout);
        resolve(window.naver.maps);
      }
    };
    window.navermap_authFailure = () => {
      fail("지도 인증을 확인하지 못했어요. 지도 키와 허용 주소를 확인해 주세요.");
      window.dispatchEvent(new Event("we2day-map-error"));
    };
    script.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(key)}&callback=we2dayMapReady`;
    script.referrerPolicy = "origin";
    script.async = true;
    // An already initialized SDK can omit its callback on a later script load.
    // The load event is also a valid readiness signal when Map is available.
    script.onload = () => {
      if (window.naver?.maps?.Map) window.we2dayMapReady?.();
      else fail("지도 구성 요소를 불러오지 못했어요. 지도를 닫았다 다시 열어 주세요.");
    };
    script.onerror = () =>
      fail("지도 스크립트에 연결하지 못했어요. 네트워크 연결을 확인해 주세요.");
    document.head.append(script);
  });
  return loading;
}
