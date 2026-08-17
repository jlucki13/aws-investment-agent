// The API returns the brief as one plain-text string. Bedrock is instructed to
// format it as "- " bullet lines with occasional **bold** spans, but neither
// of those render as anything but literal characters if dropped straight into
// a <p>. This turns that string into real <ul>/<strong> elements -- built as
// React nodes rather than injected HTML, so nothing from the model output can
// end up parsed as markup.

function renderInline(text) {
  return text
    .split(/\*\*(.+?)\*\*/g)
    .map((part, i) => (i % 2 === 1 ? <strong key={i}>{part}</strong> : part));
}

function toBlocks(text) {
  const blocks = [];
  let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = line.match(/^[-•]\s*(.*)$/);
    if (bullet) {
      if (!list) {
        list = [];
        blocks.push({ type: "ul", items: list });
      }
      list.push(bullet[1]);
    } else {
      list = null;
      blocks.push({ type: "p", text: line });
    }
  }
  return blocks;
}

export default function BriefText({
  text,
  paragraphClassName,
  listClassName,
  itemClassName,
}) {
  if (!text) return null;

  return (
    <>
      {toBlocks(text).map((block, i) =>
        block.type === "ul" ? (
          <ul key={i} className={listClassName}>
            {block.items.map((item, j) => (
              <li key={j} className={itemClassName}>
                {renderInline(item)}
              </li>
            ))}
          </ul>
        ) : (
          <p key={i} className={paragraphClassName}>
            {renderInline(block.text)}
          </p>
        )
      )}
    </>
  );
}
