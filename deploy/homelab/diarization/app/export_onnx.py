"""Export one Nemotron-3-Diarization streaming step to ONNX (static shapes, fp32)."""
import os

import sdpa_patch
import torch
from ov_diarizer import STREAM_CFG


class _Step(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, *a):
        return self.m.forward_for_export(*a)


def export(model, path):
    sdpa_patch.apply()
    sm = model.sortformer_modules
    for k, v in STREAM_CFG.items():
        setattr(sm, k, v)
    model._check_streaming_parameters()
    # NeMo downsamples inside forward_for_export, but the streaming step needs the raw high-res preds
    sm.downsample_preds = lambda p, f, **k: p
    tmp = path + ".tmp"
    try:
        with torch.no_grad():
            torch.onnx.export(_Step(model), model.streaming_input_examples(1), tmp,
                              input_names=model.input_names, output_names=model.output_names,
                              opset_version=17, dynamo=False)
    finally:
        del sm.downsample_preds  # restore the class method
    os.replace(tmp, path)
