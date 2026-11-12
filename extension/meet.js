// Adapted from reference/legacy; see licenses/legacy-MIT.txt.
// Installed at document_start in MAIN world, before Meet creates its peers.
(() => {
  if (window.__callTranslatorProbe) return;
  const NativePeer = window.RTCPeerConnection;
  const peers = new Set();
  window.RTCPeerConnection = new Proxy(NativePeer, {
    construct(Target, args, NewTarget) {
      const peer = Reflect.construct(Target, args, NewTarget);
      peers.add(peer);
      peer.addEventListener('connectionstatechange', () => {
        if (peer.connectionState === 'closed') peers.delete(peer);
      });
      return peer;
    }
  });
  function audioSenders() {
    return [...peers].flatMap(peer => peer.getSenders())
      .filter(sender => sender.track?.kind === 'audio' && sender.track.readyState === 'live' && sender.track.enabled)
      .map(sender => ({sender, track: sender.track}));
  }
  function hasAudioConnection(senders) {
    return [...peers].some(peer => peer.connectionState !== 'closed' && peer.signalingState !== 'closed' &&
      peer.getSenders().some(sender => senders.includes(sender)));
  }
  // Compatibility with the proven track replacement module; there is no
  // diagnostic beep/probe or extra microphone acquisition in this product.
  window.__callTranslatorProbe = Object.freeze({audioSenders, hasAudioConnection, restore: async () => {}});
})();
