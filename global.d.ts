import cytoscape from 'cytoscape';

declare module 'cytoscape' {
  interface NodeLayoutOptions {
    name: 'cose-bilkent';
    refresh?: number;
    fit?: boolean;
    padding?: number;
    randomize?: boolean;
    nodeRepulsion?: number;
    idealEdgeLength?: number;
    edgeElasticity?: number;
    nestingFactor?: number;
    gravity?: number;
    numIter?: number;
    coolingFactor?: number;
    initialTemp?: number;
    minTemp?: number;
    tile?: boolean;
    animate?: 'end' | 'during' | boolean;
    animationDuration?: number;
    tilingPaddingVertical?: number;
    tilingPaddingHorizontal?: number;
    gravityRangeCompound?: number;
    gravityCompound?: number;
    gravityRange?: number;
    quality?: 'draft' | 'default' | 'proof';
  }
}