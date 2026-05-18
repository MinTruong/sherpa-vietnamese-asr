Long-form clustering browser bundle
====================================

This bundle exposes `window.LongFormClustering` for the offline PWA CAM++
long-form diarization path.

Bundled from npm packages:

- `umap-js` 1.4.0, MIT
- `clusternova` 1.5.5, MIT

Transitive libraries included by the bundle are MIT licensed as well:
`ml-levenberg-marquardt`, `ml-matrix`, `ml-array-max`, `ml-array-min`,
`ml-array-rescale`, and `is-any-array`.

The bundle is generated with esbuild from:

```js
import { UMAP, cosine } from "umap-js/dist/umap";
import ClusternovaHDBSCAN, { euclidean as clusternovaEuclidean } from "clusternova";
window.LongFormClustering = {
  UMAP,
  cosine,
  ClusternovaHDBSCAN,
  clusternovaEuclidean,
};
```
