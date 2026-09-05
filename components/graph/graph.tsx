'use client';

import { useEffect, useRef } from 'react';
import cytoscape, {
  Core,
  EdgeDefinition,
  ElementDefinition,
  NodeDefinition,
} from 'cytoscape';
import coseBilkent from 'cytoscape-cose-bilkent';
import {
  FontResult,
  FontRow,
  SiteResult,
  SiteRow,
} from '@/types/schema';
import { TagType } from '@/components/display/sitefontinspector';
import { BubbleSortType } from '../filters/fontsearch-form';

// Register the layout extension once per module load.
if (typeof cytoscape('layout', 'cose-bilkent') === 'undefined') {
  cytoscape.use(coseBilkent);
}

// A palette to cycle through so each bubble gets a distinct color.
const PALETTE = [
  '#D2D7DF',
  '#BDBBB0',
  '#F7CB15',
  '#F55D3E',
  '#8A897C',
  '#F7F7F7',
  '#9EE37D',
  '#FF5154',
  '#b97abc',
];

function colorForIndex(i: number): string {
  return PALETTE[i % PALETTE.length];
}

type GraphResult = SiteResult | FontResult | undefined;

type GraphItem = {
  label: string;
  count: number;
  row?: FontRow | SiteRow;
};

function getGraphItems(fontdata: GraphResult): GraphItem[] {
  if (!fontdata) return [];
  switch (fontdata._tag) {
    case 'BubbleFontResult':
    case 'BubbleSiteResult':
      return fontdata.data.map((n) => ({
        label: `${n.label} (${n.count})`,
        count: n.count,
      }));

    case 'RowFontResult':
      return fontdata.data.map((n) => ({
        label: n.font,
        count: n.hits,
        row: n,
      }));

    case 'RowSiteResult':
      return fontdata.data.map((n) => ({
        label: n.domain,
        count: (8000 - n.rank),
        row: n,
      }));
  }
}

  const CHARS_PER_LINE = 14;
  const ROW_FONT_SIZE_MIN = 9;
  const ROW_FONT_SIZE_MAX = 18;
  const BUBBLE_FONT_SIZE_MIN = 11;
  const BUBBLE_FONT_SIZE_MAX = 22;

  function textBlockSize(label: string, fontSize: number) {
    const charWidth = fontSize * 0.62;
    const lines = Math.max(1, Math.ceil(label.length / CHARS_PER_LINE));
    const width = Math.min(label.length, CHARS_PER_LINE) * charWidth + 24;
    const height = lines * fontSize * 1.4 + 24;

    return Math.max(width, height);
  }

  function countScale(
    count: number,
    minCount: number,
    maxCount: number,
  ) {
    const range = maxCount - minCount;

    return range > 0
      ? (count - minCount) / range
      : 0.5;
  }

  function sizeForBubbleNode(
    count: number,
    minCount: number,
    maxCount: number,
    label: string,
  ) {
    const t = countScale(count, minCount, maxCount);

    const fontSize =
      BUBBLE_FONT_SIZE_MIN +
      t * (BUBBLE_FONT_SIZE_MAX - BUBBLE_FONT_SIZE_MIN);

    const countSize = 50 + t * 230;
    const size = Math.max(
      countSize,
      textBlockSize(label, fontSize),
    );

    return {
      size,
      fontSize,
      textMaxWidth: Math.max(40, size - 28),
    };
  }

  function sizeForRowNode(
    count: number,
    minCount: number,
    maxCount: number,
    label: string,
  ) {
    const t = countScale(count, minCount, maxCount);

    const fontSize =
      ROW_FONT_SIZE_MIN +
      t * (ROW_FONT_SIZE_MAX - ROW_FONT_SIZE_MIN);

    // Keep the same basic scaling behavior as category nodes,
    // but use a smaller range appropriate for individual fonts/sites.
    const countSize = 50 + t * 230;

    const size = Math.max(
      countSize,
      textBlockSize(label, fontSize),
      70,
    );

    return {
      size,
      fontSize,
      textMaxWidth: Math.max(40, size - 28),
    };
  }

  function buildElements(fontdata: GraphResult) {
    if (!fontdata) {
      return {
        nodes: [],
        edges: [],
      };
    }

    const items = getGraphItems(fontdata);

    const counts = items.map((n) => n.count);
    const minCount = counts.length
      ? Math.min(...counts)
      : 0;
    const maxCount = counts.length
      ? Math.max(...counts)
      : 1;

    const isBubbleTag =
      fontdata._tag === 'BubbleFontResult' ||
      fontdata._tag === 'BubbleSiteResult';

    const nodes: ElementDefinition[] = items.map((n, i) => {
      const dims = isBubbleTag
        ? sizeForBubbleNode(
            n.count,
            minCount,
            maxCount,
            n.label,
          )
        : sizeForRowNode(
            n.count,
            minCount,
            maxCount,
            n.label,
          );

      return {
        data: {
          id: `bubble-${i}-${n.label}`,
          label: n.label,
          count: n.count,
          color: colorForIndex(i),
          row: n.row ?? null,
          size: dims.size,
          fontSize: dims.fontSize,
          textMaxWidth: dims.textMaxWidth,
        },
      };
    });

    return {
      nodes: nodes as NodeDefinition[],
      edges: [] as EdgeDefinition[],
    };
  }


export default function CytoscapeGraph({
  fontdata,
  filter,
  tagCallback,
  catCallback,
  setter,
  onBack,
}: {
  fontdata: GraphResult;
  filter: BubbleSortType;
  tagCallback: (data: TagType, clearBefore: boolean) => void;
  catCallback: (category: string, clearBefore: boolean) => void;
  setter: (row: FontRow | SiteRow) => void;
  onBack: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  // Always-current refs so event handlers stay fresh without forcing the
  // Cytoscape instance itself to be torn down and rebuilt on every change.
  const fontdataRef = useRef(fontdata);
  const filterRef = useRef(filter);
  const tagCallbackRef = useRef(tagCallback);
  const catCallbackRef = useRef(catCallback);
  const setterRef = useRef(setter);

  useEffect(() => {
    fontdataRef.current = fontdata;
    filterRef.current = filter;
    tagCallbackRef.current = tagCallback;
    catCallbackRef.current = catCallback;
    setterRef.current = setter;
  });

  /*
   * Create the Cytoscape instance exactly once. It persists across data,
   * filter, and callback changes — only the elements get synced (below),
   * so switching views or clicking a bubble no longer blows away and
   * re-fades the whole graph.
   */
  useEffect(() => {
    if (!containerRef.current) return;
  
    const cy = cytoscape({
      container: containerRef.current,
      boxSelectionEnabled: false,
      elements: { nodes: [], edges: [] },
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            label: 'data(label)',
            'text-valign': 'center',
            'text-halign': 'center' as 'center',
            color: '#171717',
            'font-size': 'data(fontSize)',
            width: 'data(size)',
            height: 'data(size)',
            'text-wrap': 'wrap' as 'wrap',
            'text-max-width': 'data(textMaxWidth)',
            'overlay-opacity': 0,
            'transition-property': 'opacity, background-opacity',
            'transition-duration': '0.15s',
            'transition-timing-function': 'ease' as 'ease',
            'font-family': 'CommitMono, monospace',
          },
        },
        {
          // Hover state only - fully independent of the entrance fade.
          selector: 'node.hover',
          style: {
            'background-opacity': 0.5,
            cursor: 'pointer',
          },
        },
      ],
    });

    cyRef.current = cy;

    cy.on('mouseover', 'node', (evt) => evt.target.addClass('hover'));
    cy.on('mouseout', 'node', (evt) => evt.target.removeClass('hover'));
    cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      const name = (node.data('label') as string | undefined)?.split(' (')[0];
      if (!name) return;

      const row = node.data('row') as FontRow | SiteRow | null;
      if (row) {
        setterRef.current(row);
        return;
      }

      const data = fontdataRef.current;
      if (!data) return;
      if (data._tag === 'BubbleFontResult' || data._tag === 'RowFontResult') {
        tagCallbackRef.current(
          {
            label: name,
            type: filterRef.current
          } as TagType,
          false,
        );
      } else {
        catCallbackRef.current(name, false);
      }
    });


  
    return () => {
      cy.destroy();
      cyRef.current = null;
    };

  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (!fontdata) return; 
  
    const { nodes } = buildElements(fontdata);
  
    cy.startBatch();
    cy.elements().remove();
    cy.add(nodes);
    cy.endBatch();
  
    cy.resize();
  
    const layout = cy.layout({
      name: 'cose-bilkent',
      fit: true,
      padding: 40,
      randomize: true,
      animate: false,
      nodeDimensionsIncludeLabels: true,
      tile: false,
      nodeRepulsion: 9000,
      idealEdgeLength: 100,
      gravity: 0.1,
    } as any);
  
    layout.one('layoutstop', () => {
      if (!cyRef.current) return;
      cy.fit(undefined, 30);
    });
  
    layout.run();
  }, [fontdata]);

  const showBack =
  fontdata?._tag === 'RowFontResult' || fontdata?._tag === 'RowSiteResult';

return (
  <div className="graph-container" style={{ position: 'relative' }}>
    {showBack && (
      <button
        type="button"
        className="text button-not graph-back-btn"
        onClick={onBack}
        style={{ position: 'absolute', top: 1, left: 1, zIndex: 10 }}
      >
        ← back
      </button>
    )}
    <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
  </div>
);
}