// ============================================
// SERVICE WORKER - FAZENDA RECREIO
// Funciona offline e sincroniza depois
// ============================================

const CACHE_NAME = 'fazenda-recreio-v1';
const urlsParaCache = [
    '/',
    '/login',
    '/static/css/style.css',
    '/static/images/logo.png',
    '/static/images/logo-192.png',
    '/static/images/logo-512.png'
];

// ============================================
// 1. INSTALAÇÃO - Guarda os arquivos em cache
// ============================================
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function(cache) {
                console.log('✅ Arquivos em cache!');
                return cache.addAll(urlsParaCache);
            })
    );
    self.skipWaiting(); // Ativa o novo service worker imediatamente
});

// ============================================
// 2. ATIVAÇÃO - Limpa caches antigos
// ============================================
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.map(function(cache) {
                    if (cache !== CACHE_NAME) {
                        console.log('🗑️ Removendo cache antigo:', cache);
                        return caches.delete(cache);
                    }
                })
            );
        })
    );
    return self.clients.claim();
});

// ============================================
// 3. INTERCEPTAÇÃO - Responde com cache ou rede
// ============================================
self.addEventListener('fetch', function(event) {
    event.respondWith(
        caches.match(event.request)
            .then(function(response) {
                // Se encontrou no cache, retorna
                if (response) {
                    return response;
                }
                // Se não, tenta buscar na rede
                return fetch(event.request)
                    .then(function(response) {
                        // Guarda a resposta em cache para próxima vez
                        var responseClone = response.clone();
                        caches.open(CACHE_NAME)
                            .then(function(cache) {
                                cache.put(event.request, responseClone);
                            });
                        return response;
                    })
                    .catch(function() {
                        // Se offline e não está em cache, tenta retornar a página de login
                        return caches.match('/login');
                    });
            })
    );
});

// ============================================
// 4. SINCRONIZAÇÃO - Quando voltar à internet
// ============================================
self.addEventListener('sync', function(event) {
    if (event.tag === 'sync-dados') {
        event.waitUntil(sincronizarDados());
    }
});

// Função para sincronizar com o servidor
async function sincronizarDados() {
    console.log('🔄 Sincronizando dados...');
    
    try {
        // Busca os dados salvos localmente (IndexedDB/localStorage)
        // e envia para o servidor
        const response = await fetch('/sincronizar');
        const resultado = await response.json();
        console.log('✅ Dados sincronizados:', resultado);
    } catch (error) {
        console.log('❌ Erro ao sincronizar:', error);
    }
}

// ============================================
// 5. NOTIFICAÇÃO DE MENSAGENS (opcional)
// ============================================
self.addEventListener('message', function(event) {
    if (event.data === 'syncNow') {
        event.waitUntil(sincronizarDados());
    }
});
