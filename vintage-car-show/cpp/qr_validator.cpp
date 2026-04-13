#include <string>

bool isPotentialQrToken(const std::string& token) {
    return token.rfind("VCS-", 0) == 0 && token.size() > 12;
}
