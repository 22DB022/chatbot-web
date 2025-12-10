// セッション管理
let SESSION_ID;
let chatMessages = [];

// セッションIDを取得または生成
function getOrCreateSessionId() {
    let sessionId = localStorage.getItem('chat_session_id');
    
    if (!sessionId) {
        sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        localStorage.setItem('chat_session_id', sessionId);
        console.log('新しいセッションを作成:', sessionId);
    } else {
        console.log('既存のセッションを復元:', sessionId);
    }
    
    return sessionId;
}

// 会話履歴を保存
function saveChatHistory() {
    try {
        const history = {
            messages: chatMessages,
            lastUpdated: new Date().toISOString(),
            sessionId: SESSION_ID
        };
        localStorage.setItem(`chat_history_${SESSION_ID}`, JSON.stringify(history));
        console.log('💾 会話履歴を保存:', chatMessages.length + '件');
    } catch (error) {
        console.error('会話履歴の保存エラー:', error);
        
        if (error.name === 'QuotaExceededError') {
            trimChatHistory();
        }
    }
}

// 会話履歴を読み込み
function loadChatHistory() {
    try {
        const savedHistory = localStorage.getItem(`chat_history_${SESSION_ID}`);
        if (savedHistory) {
            const history = JSON.parse(savedHistory);
            chatMessages = history.messages || [];
            console.log('📂 会話履歴を復元:', chatMessages.length + '件');
            restoreMessages();
        }
    } catch (error) {
        console.error('会話履歴の読み込みエラー:', error);
        chatMessages = [];
    }
}

// 保存されたメッセージを画面に復元
function restoreMessages() {
    const chatContainer = document.getElementById('chatContainer');
    const welcomeMsg = chatContainer.querySelector('.welcome-message');
    if (welcomeMsg) welcomeMsg.remove();
    
    chatMessages.forEach(msg => {
        addMessageToUI(msg.text, msg.isUser, msg.sources || []);
    });
    
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// 古いメッセージを削除
function trimChatHistory() {
    if (chatMessages.length > 50) {
        chatMessages = chatMessages.slice(-50);
        saveChatHistory();
        console.log('🗑️ 古い会話履歴を削除しました');
    }
}

// 初期化
async function initialize() {
    SESSION_ID = getOrCreateSessionId();
    loadChatHistory();
    
    try {
        const healthResponse = await fetch('/api/health');
        const healthData = await healthResponse.json();
        
        document.getElementById('dbType').textContent = 
            `データベース: ${healthData.database} | 状態: ${healthData.status}`;

        const initResponse = await fetch('/api/init');
        const initData = await initResponse.json();

        document.getElementById('pdfCount').textContent = initData.stats.pdf_count;
        document.getElementById('totalPages').textContent = initData.stats.total_pages;
        document.getElementById('totalChunks').textContent = initData.stats.total_chunks;

        updatePdfList(initData.pdf_list);

        console.log('✅ 初期化完了');
    } catch (error) {
        console.error('❌ 初期化エラー:', error);
        showError('サーバーに接続できません');
    }
}

// PDF一覧更新
function updatePdfList(pdfList) {
    const listElement = document.getElementById('pdfList');
    
    if (!pdfList || pdfList.length === 0) {
        listElement.innerHTML = '<li style="color: #999;">PDF未登録</li>';
        return;
    }

    listElement.innerHTML = pdfList.map(pdf => `
        <li class="pdf-item">
            <div class="pdf-name">📄 ${pdf.filename}</div>
            <div class="pdf-info">
                ${pdf.page_count}ページ | ${pdf.total_chunks}チャンク<br>
                追加日: ${new Date(pdf.added_date).toLocaleDateString('ja-JP')}
            </div>
        </li>
    `).join('');
}

// エラー表示
function showError(message) {
    const errorDiv = document.getElementById('errorMessage');
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
    setTimeout(() => {
        errorDiv.style.display = 'none';
    }, 5000);
}

// メッセージをUIに追加
function addMessageToUI(text, isUser, sources = []) {
    const chatContainer = document.getElementById('chatContainer');
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
    
    messageDiv.innerHTML = `
        <div class="message-header">${isUser ? '👤 あなた' : '🤖 AIアシスタント'}</div>
        <div class="message-content">${text.replace(/\n/g, '<br>')}</div>
    `;

    chatContainer.appendChild(messageDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// メッセージ追加
function addMessage(text, isUser, sources = []) {
    const chatContainer = document.getElementById('chatContainer');
    const welcomeMsg = chatContainer.querySelector('.welcome-message');
    if (welcomeMsg) welcomeMsg.remove();

    const message = {
        text: text,
        isUser: isUser,
        sources: sources,
        timestamp: new Date().toISOString()
    };
    chatMessages.push(message);

    addMessageToUI(text, isUser, sources);
    saveChatHistory();
}

// 質問送信
async function sendQuestion() {
    const input = document.getElementById('questionInput');
    const sendButton = document.getElementById('sendButton');
    const question = input.value.trim();

    if (!question) {
        showError('質問を入力してください');
        return;
    }

    addMessage(question, true);
    input.value = '';
    sendButton.disabled = true;
    sendButton.innerHTML = '<span class="loading"></span>';

    try {
        const response = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                question: question,
                session_id: SESSION_ID
            })
        });

        if (!response.ok) throw new Error(`HTTPエラー: ${response.status}`);

        const data = await response.json();

        if (data.no_data) {
            addMessage(data.answer, false);
        } else {
            addMessage(data.answer, false, data.sources || []);
        }

    } catch (error) {
        console.error('エラー:', error);
        showError(`エラーが発生しました: ${error.message}`);
        addMessage('エラーが発生しました。もう一度お試しください。', false);
    } finally {
        sendButton.disabled = false;
        sendButton.textContent = '送信';
    }
}

// 会話リセット
async function resetConversation() {
    if (!confirm('会話履歴をリセットしますか？\n（保存された履歴も削除されます）')) return;

    try {
        await fetch('/api/reset', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: SESSION_ID })
        });

        chatMessages = [];
        localStorage.removeItem(`chat_history_${SESSION_ID}`);
        localStorage.removeItem('chat_session_id');
        SESSION_ID = getOrCreateSessionId();

        document.getElementById('chatContainer').innerHTML = `
            <div class="welcome-message">
                <h2>ようこそ！</h2>
                <p>マルチメディア検定の学習をサポートします。</p>
                <p>気になることを質問してください！</p>
            </div>
        `;

        console.log('🔄 会話をリセットしました');
    } catch (error) {
        showError('リセットに失敗しました');
    }
}

// ファイル選択時の処理
async function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showError('PDFファイルを選択してください');
        event.target.value = '';
        return;
    }
    
    if (file.size > 50 * 1024 * 1024) {
        showError('ファイルサイズが大きすぎます（最大50MB）');
        event.target.value = '';
        return;
    }
    
    if (!confirm(`"${file.name}" をアップロードしますか？\n\n処理には数分かかる場合があります。`)) {
        event.target.value = '';
        return;
    }
    
    await uploadPDF(file);
    event.target.value = '';
}

// PDFアップロード
async function uploadPDF(file) {
    const progressDiv = document.getElementById('uploadProgress');
    const progressFill = document.getElementById('progressBarFill');
    const statusText = document.getElementById('uploadStatus');
    const uploadButton = document.querySelector('.upload-button');
    
    try {
        progressDiv.style.display = 'block';
        progressFill.style.width = '0%';
        statusText.textContent = 'アップロード中...';
        uploadButton.disabled = true;
        uploadButton.style.opacity = '0.5';
        
        const formData = new FormData();
        formData.append('file', file);
        
        let progress = 0;
        const progressInterval = setInterval(() => {
            progress += 5;
            if (progress <= 90) {
                progressFill.style.width = progress + '%';
            }
        }, 500);
        
        const response = await fetch('/api/upload-pdf', {
            method: 'POST',
            body: formData
        });
        
        clearInterval(progressInterval);
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'アップロードに失敗しました');
        }
        
        const data = await response.json();
        
        progressFill.style.width = '100%';
        statusText.textContent = '✅ 登録完了！';
        statusText.style.color = '#28a745';
        
        alert(`✅ "${data.stats.filename}" を登録しました！\n\n` +
              `ページ数: ${data.stats.page_count}\n` +
              `チャンク数: ${data.stats.total_chunks}`);
        
        setTimeout(() => {
            initialize();
            progressDiv.style.display = 'none';
            progressFill.style.width = '0%';
            statusText.style.color = '#6c757d';
        }, 2000);
        
    } catch (error) {
        console.error('アップロードエラー:', error);
        showError(`アップロード失敗: ${error.message}`);
        statusText.textContent = '❌ エラー';
        statusText.style.color = '#dc3545';
        
        setTimeout(() => {
            progressDiv.style.display = 'none';
            progressFill.style.width = '0%';
            statusText.style.color = '#6c757d';
        }, 3000);
    } finally {
        uploadButton.disabled = false;
        uploadButton.style.opacity = '1';
    }
}

// Enterキーで送信
function handleKeyPress(event) {
    if (event.key === 'Enter') {
        sendQuestion();
    }
}

// ページロード時に初期化
window.addEventListener('load', initialize);
// クイックアクション機能
function sendQuickAction(actionType) {
    const input = document.getElementById('questionInput');
    const sendButton = document.getElementById('sendButton');
    
    // ボタンが無効化されている場合は処理しない
    if (sendButton.disabled) {
        return;
    }
    
    let message = '';
    
    switch(actionType) {
        case 'quiz':
            message = '問題を出してください';
            break;
        case 'term':
            message = '重要な専門用語を1つ選んで解説してください';
            break;
        case 'past':
            message = '過去問レベルの問題を1問出してください';
            break;
        default:
            return;
    }
    
    // 入力欄に表示（視覚的フィードバック）
    input.value = message;
    
    // 少し待ってから送信（ユーザーが見えるように）
    setTimeout(() => {
        sendQuestion();
    }, 300);
}
