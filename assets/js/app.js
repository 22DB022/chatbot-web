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
    const welcomeScreen = chatContainer.querySelector('.welcome-screen');
    if (welcomeScreen) welcomeScreen.remove();
    
    chatMessages.forEach(msg => {
        addMessageToUI(msg.text, msg.isUser);
    });
    
    scrollToBottom();
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
            `${healthData.database} | ${healthData.status}`;

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
        listElement.innerHTML = '<li class="pdf-loading">PDF未登録</li>';
        return;
    }

    listElement.innerHTML = pdfList.map(pdf => `
        <li class="pdf-item">
            <div class="pdf-name">📄 ${pdf.filename}</div>
            <div class="pdf-info">
                ${pdf.page_count}ページ | ${pdf.total_chunks}チャンク
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
function addMessageToUI(text, isUser) {
    const chatContainer = document.getElementById('chatContainer');
    const welcomeScreen = chatContainer.querySelector('.welcome-screen');
    if (welcomeScreen) welcomeScreen.remove();
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = isUser ? '👤' : '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerHTML = text.replace(/\n/g, '<br>');
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    
    chatContainer.appendChild(messageDiv);
    scrollToBottom();
}

// スクロールを下に
function scrollToBottom() {
    const chatWrapper = document.querySelector('.chat-wrapper');
    chatWrapper.scrollTop = chatWrapper.scrollHeight;
}

// メッセージ追加
function addMessage(text, isUser) {
    const message = {
        text: text,
        isUser: isUser,
        timestamp: new Date().toISOString()
    };
    chatMessages.push(message);
    addMessageToUI(text, isUser);
    saveChatHistory();
}

// 質問送信
async function sendQuestion() {
    const input = document.getElementById('questionInput');
    const sendButton = document.getElementById('sendButton');
    const question = input.value.trim();

    if (!question) {
        showError('メッセージを入力してください');
        return;
    }

    addMessage(question, true);
    input.value = '';
    input.style.height = 'auto';
    sendButton.disabled = true;
    
    // ローディング表示
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message bot-message';
    loadingDiv.id = 'loading-message';
    loadingDiv.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content">
            <div class="loading-dots">
                <span></span>
                <span></span>
                <span></span>
            </div>
        </div>
    `;
    document.getElementById('chatContainer').appendChild(loadingDiv);
    scrollToBottom();

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
        
        // ローディング削除
        const loading = document.getElementById('loading-message');
        if (loading) loading.remove();
        
        addMessage(data.answer, false);

    } catch (error) {
        console.error('エラー:', error);
        const loading = document.getElementById('loading-message');
        if (loading) loading.remove();
        showError(`エラーが発生しました: ${error.message}`);
        addMessage('エラーが発生しました。もう一度お試しください。', false);
    } finally {
        sendButton.disabled = false;
    }
}

// 会話リセット
async function resetConversation() {
    if (!confirm('新しいチャットを開始しますか？\n（現在の会話は保存されます）')) return;

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
            <div class="welcome-screen">
                <div class="welcome-icon">🎓</div>
                <h1 class="welcome-title">マルチメディア検定<br>学習アシスタント</h1>
                
                <div class="quick-actions-grid">
                    <button class="quick-action-card" onclick="sendQuickAction('quiz')">
                        <div class="card-icon">📝</div>
                        <div class="card-title">問題を出す</div>
                        <div class="card-desc">理解度をチェック</div>
                    </button>
                    <button class="quick-action-card" onclick="sendQuickAction('term')">
                        <div class="card-icon">📖</div>
                        <div class="card-title">専門用語解説</div>
                        <div class="card-desc">重要な用語を学ぶ</div>
                    </button>
                    <button class="quick-action-card" onclick="sendQuickAction('past')">
                        <div class="card-icon">📚</div>
                        <div class="card-title">過去問に挑戦</div>
                        <div class="card-desc">試験レベルの問題</div>
                    </button>
                </div>
            </div>
        `;

        console.log('🔄 新しいチャットを開始しました');
    } catch (error) {
        showError('リセットに失敗しました');
    }
}

// クイックアクション
function sendQuickAction(actionType) {
    const input = document.getElementById('questionInput');
    
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
    
    input.value = message;
    sendQuestion();
}

// テキストエリア自動リサイズ
function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
}

// Enterキー処理
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendQuestion();
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
    
    await uploadPDF(file);
    event.target.value = '';
}

// PDFアップロード
async function uploadPDF(file) {
    const progressDiv = document.getElementById('uploadProgress');
    const progressFill = document.getElementById('progressBarFill');
    const statusText = document.getElementById('uploadStatus');
    
    try {
        progressDiv.style.display = 'block';
        progressFill.style.width = '0%';
        statusText.textContent = 'アップロード中...';
        
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
        
        setTimeout(() => {
            initialize();
            progressDiv.style.display = 'none';
            progressFill.style.width = '0%';
        }, 2000);
        
    } catch (error) {
        console.error('アップロードエラー:', error);
        showError(`アップロード失敗: ${error.message}`);
        statusText.textContent = '❌ エラー';
        
        setTimeout(() => {
            progressDiv.style.display = 'none';
            progressFill.style.width = '0%';
        }, 3000);
    }
}

// サイドバー切り替え
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('open');
}

// ページロード時に初期化
window.addEventListener('load', initialize);