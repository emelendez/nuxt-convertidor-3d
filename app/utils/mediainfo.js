// Lectura de metadatos en cliente con mediainfo.js (WASM), si está en vendor/.
// Lee solo los bytes que MediaInfoLib pide vía File.slice — nunca el fichero
// entero. Si vendor/mediainfo no existe, devuelve null y la app usa ffprobe.
let factoryPromise = null;

async function loadFactory() {
  if (factoryPromise) return factoryPromise;
  factoryPromise = (async () => {
    try {
      const mod = await import('../vendor/mediainfo/esm/index.js');
      return mod.default || mod.mediaInfoFactory;
    } catch (_) {
      return null; // vendor no instalado: degradación silenciosa
    }
  })();
  return factoryPromise;
}

export async function readFileMetadata(file) {
  const factory = await loadFactory();
  if (!factory) return null;
  try {
    const mi = await factory({
      format: 'object', full: true,
      locateFile: (f) => `vendor/mediainfo/${f}`,
    });
    const result = await mi.analyzeData(
      () => file.size,
      async (chunkSize, offset) =>
        new Uint8Array(await file.slice(offset, offset + chunkSize).arrayBuffer()),
    );
    mi.close();
    const tracks = result?.media?.track || [];
    const gen = tracks.find(t => t['@type'] === 'General') || {};
    const vid = tracks.find(t => t['@type'] === 'Video') || {};
    return {
      duration_s: parseFloat(gen.Duration || vid.Duration || 0),
      video: {
        codec: (vid.Format || '').toLowerCase(),
        width: parseInt(vid.Width || 0),
        height: parseInt(vid.Height || 0),
        fps: parseFloat(vid.FrameRate || 0),
        bit_depth: parseInt(vid.BitDepth || 8),
        hdr: /2084|HLG|HDR/i.test(`${vid.transfer_characteristics || ''} ${vid.HDR_Format || ''}`),
        hdr_format: vid.HDR_Format || null,
      },
      audio_tracks: tracks.filter(t => t['@type'] === 'Audio')
        .map(t => ({ codec: t.Format, language: t.Language })),
      subtitle_tracks: tracks.filter(t => t['@type'] === 'Text')
        .map(t => ({ codec: t.Format, language: t.Language })),
      chapters: 0,
      is_4k: parseInt(vid.Width || 0) >= 3000,
    };
  } catch (_) {
    return null;
  }
}
