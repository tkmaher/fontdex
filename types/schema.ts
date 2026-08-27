import { Schema, Match } from "effect";

export const FontFilter = Schema.Struct({
  searchString: Schema.optional(Schema.String),
  classification: Schema.optional(Schema.String),
  styles: Schema.Array(Schema.String),
  subsets: Schema.Array(Schema.String),
  styleOr: Schema.Boolean,
  subsetOr: Schema.Boolean,
  sortBy: Schema.String,
  page: Schema.Number,
  bubbleSort: Schema.optional(Schema.String),
});
export type FontFilter = Schema.Schema.Type<typeof FontFilter>;

export const FontRow = Schema.Struct({
  font: Schema.String,
  classification: Schema.String,
  style_tags: Schema.NullOr(Schema.String),
  source: Schema.String,
  subsets: Schema.NullOr(Schema.String),
  notes: Schema.NullOr(Schema.String),
  confidence: Schema.NullOr(Schema.String),
  hits: Schema.Number,
});
export type FontRow = Schema.Schema.Type<typeof FontRow>;

export const RowFontResult = Schema.Struct ({
  data: Schema.Array(FontRow),
  rows: Schema.Number,
  pages: Schema.Number,
  _tag: Schema.Literal("RowFontResult"),
});

export const NodeData = Schema.Struct({
  label: Schema.String,
  count: Schema.Number,
});

export const BubbleFontResult = Schema.Struct ({
  data: Schema.Array(NodeData),
  _tag: Schema.Literal("BubbleFontResult"),

});
export type BubbleFontResult = Schema.Schema.Type<typeof BubbleFontResult>;


export const FontResult = Schema.Union(RowFontResult, BubbleFontResult);
export type FontResult = Schema.Schema.Type<typeof FontResult>;