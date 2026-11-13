    // Adapt only the private export runtime. Media entries remain manual-only.
    const collectViaContentSelectors = () => {
      const candidates = Array.from(root.querySelectorAll(
        'div[class*="comment-content-text-"], img.douyin-creator-interactive-image-img, [id^="semi-image-preview-group"]'
      ));
      const seen = new Set();
      const blocks = [];
      for (const candidate of candidates) {
        let container = candidate.parentElement;
        for (let depth = 0; depth < 8 && container && container !== root; depth++) {
          const names = container.querySelectorAll('div[class*="username-"]');
          if (names.length === 1) break;
          if (names.length > 1) { container = null; break; }
          container = container.parentElement;
        }
        if (!container || container === root || seen.has(container)) continue;
        const usernameEl = container.querySelector('div[class*="username-"]');
        if (!usernameEl) continue;
        const username = normalizeNameLine(Array.from(usernameEl.childNodes)
          .filter(node => node.nodeType === 3).map(node => node.textContent || '').join(''));
        const contentEl = container.querySelector('div[class*="comment-content-text-"]');
        const text = contentEl ? normalize(fullText(contentEl)) : '';
        const imageUrls = [...new Set(Array.from(container.querySelectorAll(
          'img.douyin-creator-interactive-image-img, [id^="semi-image-preview-group"] img'
        )).map(img => (img.currentSrc || img.src || '').trim()).filter(src => /^https?:\/\//.test(src)))];
        if (!username || (!text && !imageUrls.length)) continue;
        seen.add(container);
        const mediaOnly = !text;
        // CDN signatures expire; object paths provide stable media identity.
        const mediaKeys = mediaOnly ? [...new Set(imageUrls.map(src => new URL(src).pathname))].sort() : [];
        const commentText = text || '[图片/表情评论]';
        const timeEl = container.querySelector('div[class*="time-"]');
        const publishText = timeEl ? normalize(timeEl.textContent || '') : '';
        const signature = [username, commentText, publishText, ...(mediaOnly ? mediaKeys : [])].join('|');
        const domIndex = blocks.length;
        const rect = (contentEl || candidate).getBoundingClientRect();
        container.setAttribute('data-codex-comment-block', String(domIndex));
        blocks.push({domIndex, left:rect.left, top:rect.top, entry:{
          username, commentText, publishText, signature, order:domIndex,
          consumedLineCount:0, imageUrls, mediaOnly, mediaKeys
        }});
      }
      return blocks.length ? blocks : null;
    };
