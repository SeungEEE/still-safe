import torch
import torch.nn as nn

class Fall1DCNN(nn.Module):
    def __init__(self, in_channels=38, num_classes=2):
        """
            시계열 데이터를 입력받아 쓰러짐/안쓰러짐 을 반환하는 모델
            
            Args:
                x (torch.Tensor): 입력 시계열 피처 텐서, shape [B, C, T] = [B, 38, 10]
            Returns:
                torch.Tensor: 클래스별 로짓(Logits), shape [B, num_classes] = [B, 2]
        """
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(in_channels, 32, kernel_size=3, padding=1), # [B, 38, 10] -> [B, 32, 10]
            nn.BatchNorm1d(32),                                   # [B, 32, 10] -> [B, 32, 10]
            nn.ReLU(),
            nn.MaxPool1d(2),                                      # [B, 32, 10] -> [B, 32, 5]

            nn.Conv1d(32, 64, kernel_size=3, padding=1),          # [B, 32, 5]  -> [B, 64, 5]
            nn.BatchNorm1d(64),                                   # [B, 64, 5]  -> [B, 64, 5]
            nn.ReLU()
        )
        self.classifier = nn.Sequential(
            nn.Linear(64 * 5, 64),                                # [B, 64 * 5] -> [B, 64]
            nn.ReLU(),
            nn.Linear(64, num_classes)                            # [B, 64] -> [B, num_classes]
        )

    def forward(self, x):
        # x shape: [B, C, T] [B, 38, 10]
        # [배치 크기, 입력 채널 수, 시계열 스텝 수]
        
        x = self.features(x)    # [B, 38, 10] -> [B, 64, 5]
        x = x.flatten(1)       # [B, 64, 5]  -> [B, 64 * 5]
        x = self.classifier(x)  # [B, 64 * 5] -> [B, num_classes]

        return x