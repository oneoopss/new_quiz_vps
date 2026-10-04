// Проверка экспорта квиза: мульти-ответы и полное отсутствие JS в выходном HTML.
// Запуск: node check_export.mjs  (дополнительно пишет export_sample.html для инспекции)
import { readFileSync, writeFileSync } from 'node:fs';

class FakeElement {
    constructor(tag = 'div') {
        this.tag = tag;
        this.value = '';
        this._text = '';
        this.dataset = {};
        this.style = { cssText: '' };
        this.classList = { add() {}, remove() {}, contains: () => false };
        this.children = [];
    }
    set textContent(v) { this._text = String(v); }
    get textContent() { return this._text; }
    set innerHTML(v) { this._text = String(v); }
    get innerHTML() {
        return this._text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
    appendChild(c) { this.children.push(c); return c; }
    addEventListener() {}
    removeEventListener() {}
    querySelectorAll() { return []; }
    querySelector() { return new FakeElement(); }
    remove() {}
    focus() {}
    click() {}
    closest() { return null; }
    removeChild(c) { this.children = this.children.filter((x) => x !== c); }
}

const byId = new Map();
const document = {
    readyState: 'complete',
    getElementById(id) {
        if (!byId.has(id)) byId.set(id, new FakeElement());
        return byId.get(id);
    },
    createElement(tag) { return new FakeElement(tag); },
    addEventListener() {},
    body: new FakeElement('body'),
};
const localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
const window = globalThis;
globalThis.document = document;
globalThis.localStorage = localStorage;
globalThis.window = window;

// Загружаем js.js (IIFE выполнит init сразу — readyState 'complete')
const src = readFileSync(new URL('../js.js', import.meta.url), 'utf8');
eval(src);

// Вопрос 1 — один верный; вопрос 2 — НЕСКОЛЬКО верных (мульти)
window.QuizBuilder.addQuestion({
    text: 'Обычный вопрос: какой вариант верный?',
    explanation: 'Обычное пояснение.',
    options: [
        { text: 'Верный вариант', isCorrect: true },
        { text: 'Неверный вариант', isCorrect: false },
    ],
});
window.QuizBuilder.addQuestion({
    text: 'Мульти-вопрос: какие варианты верные?',
    explanation: 'Пояснение мульти-вопроса.',
    options: [
        { text: 'Верный вариант А', isCorrect: true },
        { text: 'Неверный вариант', isCorrect: false },
        { text: 'Верный вариант Б', isCorrect: true },
    ],
});

window.generateHtmlCode();
const html = document.getElementById('htmlOutput').value;
writeFileSync(new URL('./export_sample.html', import.meta.url), html);

// Цепочка «все верные выбраны» работает, если инпуты и подсказка — соседи одного
// уровня (пусть и внутри общего .options-container)
const multiChain = /#q1-opt\d+:checked~#q1-opt\d+:checked~\.answer-hint-multi\{display:block!important/.test(html);
const card1 = html.slice(html.indexOf('id="card-q1"'));
const containerSeg = card1.slice(
    card1.indexOf('class="options-container"'),
    card1.indexOf('navigation-buttons'),
);
const hintInsideContainer = containerSeg.includes('answer-hint-multi');

const checks = {
    'экспорт сформирован (HTML непустой)': html.includes('<!DOCTYPE html>'),
    'мульти-вопрос использует чекбоксы': /type="checkbox" name="q1"/.test(html),
    'одиночный вопрос остался радио': /type="radio" name="q0"/.test(html),
    'нативные инпуты скрыты стилями (нет «второго чекбокса»)': html.includes('input.answer-radio{display:none}'),
    'есть плашка «несколько верных»': html.includes('Несколько верных ответов'),
    'число верных НЕ раскрывается до ответа': !html.includes('(верных:') && !/Верных ответов: \d/.test(html),
    'в подсказке ОБА верных ответа': html.includes('Верный вариант А') && html.includes('Верный вариант Б'),
    'заголовок подсказки множественный': html.includes('Правильные ответы:'),
    'подсказка мульти гасится общим правилом': html.includes('.answer-hint-multi{display:none!important}'),
    'подсказка раскрывается по цепочке ВСЕХ верных': multiChain,
    'подсказка — сосед инпутов внутри контейнера': hintInsideContainer,
    'в экспорте НЕТ JavaScript': !html.includes('<script'),
};

let failed = 0;
for (const [name, ok] of Object.entries(checks)) {
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`);
    if (!ok) failed++;
}
console.log(failed === 0 ? '\nВСЕ ПРОВЕРКИ ЭКСПОРТА ПРОЙДЕНЫ' : `\nПРОВАЛЕНО: ${failed}`);
process.exit(failed === 0 ? 0 : 1);
