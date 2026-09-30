"""Run Nemotron-3-Diarization with the network step on OpenVINO, NeMo's streaming state logic on CPU."""
import openvino as ov
import torch

STREAM_CFG = {"chunk_len": 340, "chunk_right_context": 40, "fifo_len": 40, "spkcache_update_period": 300}


class OVDiarizer:
    def __init__(self, model, onnx_path, device="GPU", precision=None):
        self.m = model
        sm = model.sortformer_modules
        for k, v in STREAM_CFG.items():
            setattr(sm, k, v)
        model._check_streaming_parameters()
        model.async_streaming = True     # fixed-capacity state == the exported graph's static shapes
        model.async_pad_to_max = True
        props = {"PERFORMANCE_HINT": "LATENCY"}
        if precision:
            props["INFERENCE_PRECISION_HINT"] = precision
        self.req = ov.Core().compile_model(onnx_path, device, props).create_infer_request()
        self.chunk_frames = (sm.chunk_left_context + sm.chunk_len + sm.chunk_right_context) * model.encoder.subsampling_factor
        self._state = None
        self._out = None

        step = model.forward_streaming_step
        def step_hook(*a, **kw):
            self._state = kw["streaming_state"]
            return step(*a, **kw)
        model.forward_streaming_step = step_hook
        model._call_pre_encode = self._pre_encode
        model.frontend_encoder = lambda processed_signal, processed_signal_length, bypass_pre_encode=False: (None, processed_signal_length)
        model.forward_infer = lambda emb_seq, emb_seq_length, return_logits=False: self._out[0]

    def _pre_encode(self, features, lengths):
        st = self._state
        n = features.shape[1]
        chunk = torch.zeros((features.shape[0], self.chunk_frames, features.shape[2]))
        chunk[:, :n] = features[:, : self.chunk_frames]
        inputs = [chunk, lengths.to(torch.long), st.spkcache, st.spkcache_lengths, st.fifo, st.fifo_lengths]
        self.req.infer({i: t.detach().cpu().numpy() for i, t in enumerate(inputs)})
        preds, embs, elen = (torch.from_numpy(self.req.get_output_tensor(i).data.copy()) for i in range(3))
        elen = elen.to(torch.long)
        self._out = (preds,)
        return embs[:, : int(elen.max())], elen

    def diarize(self, audio, batch_size=1):
        return self.m.diarize(audio=audio, batch_size=batch_size)
